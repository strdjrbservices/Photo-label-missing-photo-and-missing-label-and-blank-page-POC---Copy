import os
import shutil
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.views.decorators.http import require_POST
from django.core.files.storage import FileSystemStorage

from .models import ReportAudit, AuditPhotoSlot, AuditBlankPage
from .forms import ReportAuditForm
from .services import run_audit_service


def index_view(request):
    """Main dashboard displaying recent audits, metrics, and upload form."""
    form = ReportAuditForm()
    recent_audits = ReportAudit.objects.all().order_by('-created_at')

    # Aggregate stats
    total_audits = recent_audits.count()
    completed_audits = recent_audits.filter(status='COMPLETED')
    total_photos = sum(a.total_slots_scanned for a in completed_audits)
    total_missing_labels = sum(a.missing_label_count for a in completed_audits)
    total_blanks = sum(a.blank_pages_count for a in completed_audits)

    context = {
        'form': form,
        'recent_audits': recent_audits,
        'stats': {
            'total_audits': total_audits,
            'total_photos': total_photos,
            'total_missing_labels': total_missing_labels,
            'total_blanks': total_blanks,
        }
    }
    return render(request, 'audit_app/index.html', context)


def audit_create_view(request):
    """Processes appraisal report upload and triggers audit."""
    if request.method == 'POST':
        form = ReportAuditForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data.get('report_file')
            task_choice = form.cleaned_data.get('tasks', 'all')
            tasks = [task_choice] if task_choice != 'all' else ['all']

            original_filename = uploaded_file.name
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'uploads'))
            saved_name = fs.save(original_filename, uploaded_file)
            target_file_path = fs.path(saved_name)

            try:
                audit = run_audit_service(
                    file_path=target_file_path,
                    original_filename=original_filename,
                    tasks=tasks
                )
                messages.success(request, f"Successfully analyzed '{original_filename}' in {audit.execution_time_seconds}s!")
                return redirect('audit_detail', audit_id=audit.id)
            except Exception as e:
                messages.error(request, f"Error processing report: {str(e)}")
                return redirect('audit_index')
        else:
            recent_audits = ReportAudit.objects.all().order_by('-created_at')
            return render(request, 'audit_app/index.html', {'form': form, 'recent_audits': recent_audits})

    return redirect('audit_index')


def audit_detail_view(request, audit_id):
    """Detailed audit results page: summary, photo gallery, missing labels, and blank pages."""
    audit = get_object_or_404(ReportAudit, id=audit_id)
    # Exclude unused empty slots (where both image and label are missing)
    photo_slots = audit.photo_slots.exclude(has_image=False, raw_label='').exclude(has_image=False, status='EMPTY_SLOT').order_by('page_number', 'slot_name')
    blank_pages = audit.blank_pages.all().order_by('page_number')

    # Filters
    category_filter = request.GET.get('category', 'all').strip()
    status_filter = request.GET.get('status', 'all').strip()

    filtered_photos = photo_slots
    if status_filter == 'missing_label':
        filtered_photos = filtered_photos.filter(is_missing_label=True)
    elif status_filter == 'labeled':
        filtered_photos = filtered_photos.filter(status='LABELED')
    elif status_filter == 'blurry':
        filtered_photos = filtered_photos.filter(is_blurry=True)

    if category_filter and category_filter != 'all':
        filtered_photos = filtered_photos.filter(normalized_label__icontains=category_filter)

    # Categories count for tabs/chips
    categories = {}
    for slot in photo_slots:
        if slot.normalized_label:
            categories[slot.normalized_label] = categories.get(slot.normalized_label, 0) + 1

    # Photo Slots & Breakdown by Group
    basement_keywords = ['basement', 'bsmt', 'cellar', 'lower level', 'rec room', 'recreation room', 'below grade']
    basement_photos = []
    basement_bedroom_photos = []
    basement_bath_photos = []
    basement_rec_photos = []
    basement_other_photos = []
    bedroom_photos = []
    bathroom_photos = []
    garage_photos = []
    subject_exterior_photos = []
    total_room_photos = []

    def _classify_slot(slot):
        raw_l = (slot.raw_label or '').lower()
        norm_l = (slot.normalized_label or '').lower()

        is_bsmt = any(w in raw_l or w in norm_l for w in basement_keywords)
        is_bed = any(b in raw_l for b in ['bedroom', 'bed', 'bdrm', 'br']) or norm_l == 'bedroom'
        is_bath = any(b in raw_l for b in ['bath', 'bathroom', 'bth', 'lavatory', 'powder']) or norm_l == 'bathroom'
        is_rec = any(w in raw_l for w in ['rec', 'recreation', 'playroom']) or (is_bsmt and any(w in raw_l for w in ['living', 'family', 'den']))
        is_comp = any(c in raw_l or c in norm_l for c in ['comparable', 'comp ', 'rental'])
        is_garage = (any(g in raw_l or g in norm_l for g in ['garage', 'carport']) or norm_l == 'garage') and not is_comp
        is_subject_exterior = (
            norm_l in ['exterior front', 'exterior rear', 'street view']
            or any(k in raw_l for k in ['front view', 'rear view', 'street scene', 'subject front', 'subject rear', 'subject street'])
        ) and not is_comp

        groups = []
        if is_bsmt:
            if is_bed:
                groups.append('basement_br')
            elif is_bath:
                groups.append('basement_ba')
            elif is_rec:
                groups.append('basement_rr')
            else:
                groups.append('basement_other')
        if is_bed:
            groups.append('bedrooms')
        if is_bath:
            groups.append('bathrooms')
        if is_garage:
            groups.append('garage')
        if is_subject_exterior:
            groups.append('subject_exterior')

        excluded_from_total_rooms = is_bed or is_bath or (is_bsmt and is_rec) or (is_bsmt and is_bed) or (is_bsmt and is_bath)
        is_room_keyword = any(k in raw_l or k in norm_l for k in [
            'kitchen', 'living', 'dining', 'family', 'den', 'office', 'sunroom',
            'solarium', 'mudroom', 'mud room',
            'foyer', 'hall', 'room', 'area', 'nook', 'great room', 'library', 'bonus', 'loft'
        ])

        if not excluded_from_total_rooms and (is_room_keyword or norm_l in ['kitchen', 'living room', 'dining room', 'family room', 'den', 'office', 'solarium', 'mudroom']):
            groups.append('total_rooms')

        return groups

    for slot in photo_slots:
        groups = _classify_slot(slot)
        slot.group_tags = " ".join(groups)
        if any(g in groups for g in ['basement_br', 'basement_ba', 'basement_rr', 'basement_other']):
            basement_photos.append(slot)
        if 'basement_br' in groups:
            basement_bedroom_photos.append(slot)
        if 'basement_ba' in groups:
            basement_bath_photos.append(slot)
        if 'basement_rr' in groups:
            basement_rec_photos.append(slot)
        if 'basement_other' in groups:
            basement_other_photos.append(slot)
        if 'bedrooms' in groups:
            bedroom_photos.append(slot)
        if 'bathrooms' in groups:
            bathroom_photos.append(slot)
        if 'garage' in groups:
            garage_photos.append(slot)
        if 'subject_exterior' in groups:
            subject_exterior_photos.append(slot)
        if 'total_rooms' in groups:
            total_room_photos.append(slot)

    filtered_photos_list = list(filtered_photos)
    for slot in filtered_photos_list:
        slot.group_tags = " ".join(_classify_slot(slot))

    missing_labels_list = photo_slots.filter(is_missing_label=True)
    flagged_blanks = blank_pages.filter(is_blank=True)

    reconciliation = _build_reconciliation(
        audit=audit,
        bedroom_photos=bedroom_photos,
        bathroom_photos=bathroom_photos,
        basement_photos=basement_photos,
        basement_rec_photos=basement_rec_photos,
        basement_bedroom_photos=basement_bedroom_photos,
        basement_bath_photos=basement_bath_photos,
        basement_other_photos=basement_other_photos,
    )

    context = {
        'audit': audit,
        'photo_slots': filtered_photos_list,
        'all_photo_slots': photo_slots,
        'missing_labels_list': missing_labels_list,
        'blank_pages': blank_pages,
        'flagged_blanks': flagged_blanks,
        'categories': categories,
        'selected_category': category_filter,
        'selected_status': status_filter,
        'bedroom_photos': bedroom_photos,
        'bathroom_photos': bathroom_photos,
        'garage_photos': garage_photos,
        'subject_exterior_photos': subject_exterior_photos,
        'total_room_photos': total_room_photos,
        'basement_photos': basement_photos,
        'basement_bedroom_photos': basement_bedroom_photos,
        'basement_bath_photos': basement_bath_photos,
        'basement_rec_photos': basement_rec_photos,
        'basement_other_photos': basement_other_photos,
        'reconciliation': reconciliation,
    }
    return render(request, 'audit_app/detail.html', context)


def _expected_bath_rooms(val):
    """Converts UAD bath count (e.g. 1.1 -> 1 full + 1 half = 2 rooms, 1.5 -> 2 rooms)."""
    whole = int(val)
    tenths = int(round((val - whole) * 10))
    return whole + (1 if tenths == 5 else tenths)


def _build_reconciliation(
    audit,
    bedroom_photos,
    bathroom_photos,
    basement_photos,
    basement_rec_photos,
    basement_bedroom_photos,
    basement_bath_photos,
    basement_other_photos,
):
    """Computes accurate per-section values and truthful audit statuses across all 4 sources."""
    raw_meta = (audit.raw_data or {}).get("summary", {}).get("xml_property_metadata", {})
    sections = raw_meta.get("sections", {})
    sk = sections.get("sketch", {})
    imp = sections.get("improvements", {})
    grid = sections.get("sales_grid", {})
    has_sections = bool(sections)

    SUCCESS = ("bg-success-subtle text-success border border-success", "bi-check-circle-fill")
    WARNING = ("bg-warning-subtle text-warning border border-warning", "bi-exclamation-triangle-fill")
    DANGER = ("bg-danger-subtle text-danger border border-danger", "bi-x-circle-fill")
    INFO = ("bg-info-subtle text-info border border-info", "bi-info-circle-fill")
    NEUTRAL = ("bg-secondary-subtle text-secondary border border-secondary", "bi-dash-circle")

    # 1. GLA / GBA
    sketch_gla = sk.get("gla")
    imp_gla = imp.get("gla") if has_sections else audit.gross_living_area
    grid_gla = grid.get("gla") if has_sections else audit.gross_living_area
    gla_vals = [v for v in (sketch_gla, imp_gla, grid_gla) if v is not None and v > 0]
    if not gla_vals:
        gla_status, (gla_cls, gla_icon) = "N/A", NEUTRAL
    elif len(gla_vals) == 1:
        gla_status, (gla_cls, gla_icon) = "Single Source", INFO
    elif max(gla_vals) - min(gla_vals) <= 5:
        gla_status = "3-Way Match" if len(gla_vals) == 3 else "Matched"
        gla_cls, gla_icon = SUCCESS
    else:
        diff = int(round(max(gla_vals) - min(gla_vals)))
        gla_status, (gla_cls, gla_icon) = f"Variance ({diff} sf)", DANGER

    # 2. Bedrooms
    sketch_beds = sk.get("bedrooms")
    imp_beds = imp.get("bedrooms") if imp.get("bedrooms") is not None else audit.total_bedrooms
    grid_beds = grid.get("bedrooms") if has_sections else audit.total_bedrooms
    bed_form_vals = [v for v in (sketch_beds, imp_beds, grid_beds) if v is not None]
    photo_beds = len(bedroom_photos)
    if not bed_form_vals:
        bed_status, (bed_cls, bed_icon) = "N/A", NEUTRAL
    elif len(set(bed_form_vals)) > 1:
        bed_status, (bed_cls, bed_icon) = "Form Discrepancy", DANGER
    elif bed_form_vals[0] == photo_beds:
        bed_status = "4-Way Match" if len(bed_form_vals) == 3 else ("3-Way Match" if len(bed_form_vals) == 2 else "Photo Match")
        bed_cls, bed_icon = SUCCESS
    else:
        bed_status, (bed_cls, bed_icon) = "Photo Variance", WARNING

    # 3. Bathrooms
    sketch_baths = sk.get("bathrooms")
    imp_baths = imp.get("bathrooms") if imp.get("bathrooms") is not None else audit.total_bathrooms
    grid_baths = grid.get("bathrooms") if has_sections else audit.total_bathrooms
    bath_form_vals = [v for v in (sketch_baths, imp_baths, grid_baths) if v is not None]
    photo_baths = len(bathroom_photos)
    if not bath_form_vals:
        bath_status, (bath_cls, bath_icon) = "N/A", NEUTRAL
    elif len(set(round(float(v), 2) for v in bath_form_vals)) > 1:
        bath_status, (bath_cls, bath_icon) = "Form Discrepancy", DANGER
    else:
        declared_bath = float(bath_form_vals[0])
        expected_bath = _expected_bath_rooms(declared_bath)
        if photo_baths < int(declared_bath):
            bath_status, (bath_cls, bath_icon) = "Missing Bath Photos", WARNING
        elif photo_baths == expected_bath:
            bath_status, (bath_cls, bath_icon) = "Verified Match", SUCCESS
        else:
            bath_status, (bath_cls, bath_icon) = "Photo Variance", WARNING

    # 4. Total Rooms
    sketch_rooms = sk.get("rooms")
    imp_rooms = imp.get("rooms") if imp.get("rooms") is not None else audit.total_rooms
    grid_rooms = grid.get("rooms") if has_sections else audit.total_rooms
    room_form_vals = [v for v in (sketch_rooms, imp_rooms, grid_rooms) if v is not None]
    photo_rooms = audit.room_photos_identified
    if not room_form_vals:
        room_status, (room_cls, room_icon) = "N/A", NEUTRAL
    elif len(set(room_form_vals)) > 1:
        room_status, (room_cls, room_icon) = "Form Discrepancy", DANGER
    elif room_form_vals[0] == photo_rooms:
        room_status, (room_cls, room_icon) = "Verified Match", SUCCESS
    else:
        room_status, (room_cls, room_icon) = "Photo Variance", WARNING

    # 5. Basement Rooms Below Grade
    sketch_bsmt_sqft = sk.get("basement_sqft")
    imp_bsmt_sqft = audit.basement_total_sqft if audit.basement_total_sqft is not None else imp.get("basement_sqft")
    imp_bsmt_fin = audit.basement_finished_sqft
    bsmt_photo_total = len(basement_photos)
    bsmt_photo_rec = len(basement_rec_photos)
    bsmt_photo_bed = len(basement_bedroom_photos)
    bsmt_photo_bath = len(basement_bath_photos)
    bsmt_photo_other = len(basement_other_photos)

    if audit.basement_rr is None and not audit.basement_rooms_summary and imp_bsmt_sqft is None:
        if bsmt_photo_total > 0:
            bsmt_status, (bsmt_cls, bsmt_icon) = "Unlisted Photos", WARNING
        else:
            bsmt_status, (bsmt_cls, bsmt_icon) = "N/A", NEUTRAL
    elif imp_bsmt_sqft == 0 and audit.basement_rr is None:
        if bsmt_photo_total == 0:
            bsmt_status, (bsmt_cls, bsmt_icon) = "No Basement", SUCCESS
        else:
            bsmt_status, (bsmt_cls, bsmt_icon) = "Photo Variance", WARNING
    elif audit.basement_rr is not None:
        matches_all = (
            bsmt_photo_rec == (audit.basement_rr or 0)
            and bsmt_photo_bed == (audit.basement_br or 0)
            and bsmt_photo_bath >= int(audit.basement_ba or 0)
            and bsmt_photo_other == (audit.basement_other or 0)
        )
        if matches_all:
            bsmt_status, (bsmt_cls, bsmt_icon) = "Grid ↔ Photo Match", SUCCESS
        else:
            bsmt_status, (bsmt_cls, bsmt_icon) = "Photo Variance", WARNING
    else:
        bsmt_status, (bsmt_cls, bsmt_icon) = "Grid Verified", INFO

    return {
        "gla": {
            "sketch": sketch_gla,
            "sketch_page": sk.get("page"),
            "imp": imp_gla,
            "grid": grid_gla,
            "status": gla_status,
            "badge_cls": gla_cls,
            "icon": gla_icon,
        },
        "bedrooms": {
            "sketch": sketch_beds,
            "imp": imp_beds,
            "grid": grid_beds,
            "photos": photo_beds,
            "status": bed_status,
            "badge_cls": bed_cls,
            "icon": bed_icon,
        },
        "bathrooms": {
            "sketch": sketch_baths,
            "imp": imp_baths,
            "grid": grid_baths,
            "photos": photo_baths,
            "status": bath_status,
            "badge_cls": bath_cls,
            "icon": bath_icon,
        },
        "total_rooms": {
            "sketch": sketch_rooms,
            "imp": imp_rooms,
            "grid": grid_rooms,
            "photos": photo_rooms,
            "status": room_status,
            "badge_cls": room_cls,
            "icon": room_icon,
        },
        "basement": {
            "sketch_sqft": sketch_bsmt_sqft,
            "imp_sqft": imp_bsmt_sqft,
            "imp_fin_sqft": imp_bsmt_fin,
            "photo_total": bsmt_photo_total,
            "photo_rec": bsmt_photo_rec,
            "photo_bed": bsmt_photo_bed,
            "photo_bath": bsmt_photo_bath,
            "photo_other": bsmt_photo_other,
            "status": bsmt_status,
            "badge_cls": bsmt_cls,
            "icon": bsmt_icon,
        },
    }


def _permanently_delete_audit(audit):
    """Deletes all media files, directories, and the model instance from disk and database."""
    audit_id_str = str(audit.id)
    for sub in ['extracted_photos', 'audit_reports', 'blank_previews']:
        d_path = os.path.join(settings.MEDIA_ROOT, sub, audit_id_str)
        if os.path.exists(d_path):
            shutil.rmtree(d_path, ignore_errors=True)
    for field_name in ['original_file', 'excel_report', 'json_report']:
        try:
            f = getattr(audit, field_name, None)
            if f:
                f.delete(save=False)
        except Exception:
            pass
    if audit.extracted_pdf_path:
        pdf_path = os.path.join(settings.MEDIA_ROOT, 'uploads', os.path.basename(audit.extracted_pdf_path))
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
    audit.delete()


def audit_delete_view(request, audit_id):
    """Deletes a single audit and its media artifacts on disk, then redirects to index."""
    audit = get_object_or_404(ReportAudit, id=audit_id)
    fname = audit.file_name
    _permanently_delete_audit(audit)
    messages.success(request, f"Permanently deleted audit report for '{fname}'.")
    return redirect('audit_index')


def audit_bulk_delete_view(request):
    """Deletes multiple selected audits or clears all audits permanently."""
    action = request.POST.get('action') or request.GET.get('action', 'delete_selected')
    selected_ids = request.POST.getlist('selected_ids') or request.GET.getlist('selected_ids')

    if action == 'clear_all':
        audits = list(ReportAudit.objects.all())
        count = len(audits)
        if count > 0:
            for a in audits:
                _permanently_delete_audit(a)
            messages.success(request, f"Permanently cleared all {count} audit report(s) and storage.")
        else:
            messages.info(request, "No audit reports to clear.")
        return redirect('audit_index')

    if not selected_ids:
        messages.warning(request, "No audit reports were selected for deletion.")
        return redirect('audit_index')

    audits = list(ReportAudit.objects.filter(id__in=selected_ids))
    count = len(audits)
    for a in audits:
        _permanently_delete_audit(a)

    messages.success(request, f"Permanently deleted {count} selected audit report(s).")
    return redirect('audit_index')


def quick_sample_audit_view(request, sample_name=None):
    """Fallback redirect to index."""
    return redirect('audit_index')

