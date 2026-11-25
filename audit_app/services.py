import os
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.core.files import File
import pymupdf

from appraisal_analyzer import AppraisalReportPipeline
from .models import ReportAudit, AuditPhotoSlot, AuditBlankPage


def run_audit_service(
    file_path: str,
    original_filename: str,
    tasks: Optional[List[str]] = None,
    audit_instance: Optional[ReportAudit] = None
) -> ReportAudit:
    """
    Executes the appraisal audit pipeline and persists all findings into the database.
    """
    tasks = tasks or ['all']

    if audit_instance is None:
        audit = ReportAudit.objects.create(
            file_name=original_filename,
            report_type='XML' if original_filename.lower().endswith('.xml') else 'PDF',
            status='PROCESSING'
        )
    else:
        audit = audit_instance
        audit.status = 'PROCESSING'
        audit.error_message = None
        audit.save()

    start_time = time.time()

    try:
        # Prepare output directories
        audit_id_str = str(audit.id)
        photos_dir = os.path.join(settings.MEDIA_ROOT, 'extracted_photos', audit_id_str)
        reports_dir = os.path.join(settings.MEDIA_ROOT, 'audit_reports', audit_id_str)
        previews_dir = os.path.join(settings.MEDIA_ROOT, 'blank_previews', audit_id_str)

        os.makedirs(photos_dir, exist_ok=True)
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(previews_dir, exist_ok=True)

        # Execute core pipeline
        pipeline = AppraisalReportPipeline()
        report_data = pipeline.run(file_path, tasks=tasks, output_dir=photos_dir)

        summary = report_data.get('summary', {})
        findings = summary.get('findings', {})
        xml_meta = summary.get('xml_property_metadata', {})
        photo_details = report_data.get('photo_details', {})
        blank_details = report_data.get('blank_details', [])

        # Update audit instance with XML / PDF metadata
        audit.property_address = xml_meta.get('address') or xml_meta.get('property_address')
        audit.city = xml_meta.get('city')
        audit.state = xml_meta.get('state')
        audit.postal_code = xml_meta.get('zip_code') or xml_meta.get('postal_code')
        audit.total_rooms = xml_meta.get('total_rooms')
        audit.total_bedrooms = xml_meta.get('bedrooms') if xml_meta.get('bedrooms') is not None else xml_meta.get('total_bedrooms')
        audit.total_bathrooms = xml_meta.get('bathrooms') if xml_meta.get('bathrooms') is not None else xml_meta.get('total_bathrooms')
        audit.gross_living_area = xml_meta.get('gross_living_area')
        audit.appraised_value = str(xml_meta.get('appraised_value')) if xml_meta.get('appraised_value') is not None else None

        # Basement Grid Analysis
        audit.basement_rr = xml_meta.get('basement_rr')
        audit.basement_br = xml_meta.get('basement_br')
        audit.basement_ba = xml_meta.get('basement_ba')
        audit.basement_other = xml_meta.get('basement_other')
        audit.basement_total_sqft = xml_meta.get('basement_total_sqft')
        audit.basement_finished_sqft = xml_meta.get('basement_finished_sqft')
        audit.basement_rooms_summary = xml_meta.get('basement_rooms_summary')

        # Statistics
        p_task = findings.get('task1_photo_and_label_inventory', {})
        m_task = findings.get('task2_missing_photo_labels', {})
        b_task = findings.get('task3_blank_pages', {})

        audit.total_slots_scanned = p_task.get('total_photo_slots', photo_details.get('total_slots_scanned', 0))
        audit.labeled_photos_count = p_task.get('labeled_photos_count', photo_details.get('labeled_photos_count', 0))
        audit.bedroom_photos_identified = p_task.get('bedroom_photos_identified', photo_details.get('bedroom_photos_identified', 0))
        audit.bathroom_photos_identified = p_task.get('bathroom_photos_identified', photo_details.get('bathroom_photos_identified', 0))
        audit.missing_label_count = m_task.get('missing_label_count', photo_details.get('missing_label_count', 0))
        audit.total_pages_scanned = b_task.get('total_pages_scanned', len(blank_details))
        audit.blank_pages_count = b_task.get('blank_pages_count', len([b for b in blank_details if b.get('is_blank')]))

        audit.extracted_pdf_path = summary.get('pdf_analyzed')
        audit.execution_time_seconds = round(time.time() - start_time, 2)

        # Generate Excel Report
        excel_filename = f"{Path(original_filename).stem}_audit_report.xlsx"
        excel_full_path = os.path.join(reports_dir, excel_filename)
        pipeline.generate_excel(report_data, excel_full_path)
        audit.excel_report.name = f"audit_reports/{audit_id_str}/{excel_filename}"

        # Generate JSON Report
        json_filename = f"{Path(original_filename).stem}_analysis.json"
        json_full_path = os.path.join(reports_dir, json_filename)
        with open(json_full_path, 'w', encoding='utf-8') as jf:
            json.dump(report_data, jf, indent=2, default=str)
        audit.json_report.name = f"audit_reports/{audit_id_str}/{json_filename}"

        audit.raw_data = report_data

        # Clear existing items if re-processing
        audit.photo_slots.all().delete()
        audit.blank_pages.all().delete()

        # Save Photo Slots to DB
        slots = photo_details.get('slots', [])
        photo_objects = []
        for s in slots:
            has_image = bool(s.get('has_image'))
            raw_label = s.get('raw_label', '') or ''
            status = s.get('status', 'EMPTY_SLOT')

            # Omit empty slots where both image and label are missing
            if not has_image and (not raw_label or raw_label == '[MISSING LABEL]' or status == 'EMPTY_SLOT'):
                continue

            full_photo_path = s.get('photo_path')
            rel_photo_path = None
            if full_photo_path and os.path.exists(full_photo_path):
                # Make relative to media root
                rel_photo_path = os.path.relpath(full_photo_path, settings.MEDIA_ROOT).replace('\\', '/')

            img_q = s.get('image_quality') or {}
            photo_objects.append(
                AuditPhotoSlot(
                    report=audit,
                    page_number=s.get('page_number', 1),
                    slot_name=s.get('slot_name', 'Slot'),
                    raw_label=s.get('raw_label', '') or '',
                    normalized_label=s.get('normalized_label', '') or '',
                    status=s.get('status', 'EMPTY_SLOT'),
                    has_image=bool(s.get('has_image')),
                    is_missing_label=bool(s.get('is_missing_label')),
                    image_relative_path=rel_photo_path,
                    width=img_q.get('width'),
                    height=img_q.get('height'),
                    aspect_ratio=img_q.get('aspect_ratio'),
                    blur_score=img_q.get('blur_score'),
                    brightness=img_q.get('brightness'),
                    is_blurry=bool(img_q.get('is_blurry', False)),
                    verification_note=s.get('verification_note', '') or ''
                )
            )
        if photo_objects:
            AuditPhotoSlot.objects.bulk_create(photo_objects)

        # Save Blank Pages to DB and generate visual thumbnails
        pdf_candidate = summary.get('pdf_analyzed')
        # Resolve full path to PDF
        doc = None
        try:
            if pdf_candidate:
                if os.path.isabs(pdf_candidate) and os.path.exists(pdf_candidate):
                    doc = pymupdf.open(pdf_candidate)
                elif os.path.exists(os.path.join(os.path.dirname(file_path), pdf_candidate)):
                    doc = pymupdf.open(os.path.join(os.path.dirname(file_path), pdf_candidate))
                elif os.path.exists(os.path.join(settings.BASE_DIR, pdf_candidate)):
                    doc = pymupdf.open(os.path.join(settings.BASE_DIR, pdf_candidate))
        except Exception:
            doc = None

        blank_objects = []
        for b in blank_details:
            p_num = b.get('page_number', 1)
            rel_preview_path = None

            # Render preview image for flagged blank pages (or sample)
            if b.get('is_blank') and doc is not None and (p_num - 1) < len(doc):
                try:
                    page = doc[p_num - 1]
                    pix = page.get_pixmap(dpi=75)
                    preview_filename = f"blank_p{p_num}.png"
                    preview_full_path = os.path.join(previews_dir, preview_filename)
                    pix.save(preview_full_path)
                    rel_preview_path = os.path.relpath(preview_full_path, settings.MEDIA_ROOT).replace('\\', '/')
                except Exception:
                    pass

            header_list = b.get('sample_header', [])
            sample_header_str = " | ".join(header_list) if isinstance(header_list, list) else str(header_list)

            blank_objects.append(
                AuditBlankPage(
                    report=audit,
                    page_number=p_num,
                    is_blank=bool(b.get('is_blank')),
                    classification=b.get('classification', 'NON_BLANK'),
                    content_pixel_pct=b.get('content_pixel_pct', 0.0),
                    laplacian_var=b.get('laplacian_var', 0.0),
                    edge_density_pct=b.get('edge_density_pct', 0.0),
                    total_text_lines=b.get('total_text_lines', 0),
                    sample_header=sample_header_str,
                    preview_relative_path=rel_preview_path
                )
            )

        if doc:
            doc.close()

        if blank_objects:
            AuditBlankPage.objects.bulk_create(blank_objects)

        audit.status = 'COMPLETED'
        audit.save()

    except Exception as e:
        audit.status = 'FAILED'
        audit.error_message = str(e)
        audit.execution_time_seconds = round(time.time() - start_time, 2)
        audit.save()
        raise e

    return audit
