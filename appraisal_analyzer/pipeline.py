"""
pipeline.py
Main orchestrator that executes appraisal verification tasks:
1. Extract photos and labels, and identify bedroom & bathroom photos.
2. Detect missing labels for photos.
3. Detect blank pages.
"""

import os
import json
import time
from typing import Dict, Any, Optional

from .xml_parser import XMLAppraisalParser
from .photo_verifier import PhotoVerifier
from .blank_detector import BlankPageDetector


def extract_pdf_form_metrics(pdf_path: str) -> dict:
    """Extracts finished area room counts (Total Rooms, Beds, Baths, GLA) directly from appraisal form text."""
    metrics = {}
    doc = None
    try:
        doc = pymupdf.open(pdf_path)
        for p_idx in range(min(5, len(doc))):
            page = doc[p_idx]
            text = page.get_text()
            if "finished area above grade contains" in text.lower():
                words = page.get_text("words")
                y_target = None
                for w in words:
                    if "contains:" in w[4].lower():
                        y_target = w[1]
                        break
                if y_target:
                    lw = [w for w in words if abs(w[1] - y_target) < 6]
                    lw.sort(key=lambda w: w[0])
                    for idx, w in enumerate(lw):
                        wl = w[4].lower()
                        if wl in ["rooms", "rooms:"] and idx > 0:
                            v = lw[idx - 1][4].replace(",", "")
                            if v.isdigit():
                                metrics["total_rooms"] = int(v)
                        elif "bedroom" in wl and idx > 0:
                            v = lw[idx - 1][4].replace(",", "")
                            if v.isdigit():
                                metrics["bedrooms"] = int(v)
                        elif "bath" in wl and idx > 0:
                            try:
                                metrics["bathrooms"] = float(lw[idx - 1][4].replace(",", ""))
                            except Exception:
                                pass
                        elif "square" in wl and idx > 0:
                            try:
                                metrics["gross_living_area"] = float(lw[idx - 1][4].replace(",", ""))
                            except Exception:
                                pass
                    if metrics.get("total_rooms"):
                        break
    except Exception:
        pass
    finally:
        if doc:
            doc.close()
    return metrics


class AppraisalReportPipeline:
    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self.blank_detector = BlankPageDetector()
        self.photo_verifier = PhotoVerifier()

    def run(self, file_path: str, tasks: Optional[list] = None, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes analysis on an XML file (or direct PDF).
        tasks: list of tasks to run e.g. ['photos', 'blank'] or None for all.
        output_dir: optional custom directory for saved extracted photos.
        """
        start_time = time.time()
        file_ext = os.path.splitext(file_path)[1].lower()
        active_tasks = [t.lower() for t in tasks] if tasks else ["all"]

        run_photos = "all" in active_tasks or any(
            t in active_tasks
            for t in ["photos", "photo", "labels", "missing_labels", "1", "2"]
        )
        run_blank = "all" in active_tasks or any(
            t in active_tasks for t in ["blank", "blanks", "blank_pages", "3"]
        )

        xml_metadata = {}
        pdf_path = file_path

        if file_ext == ".xml":
            xml_parser = XMLAppraisalParser(file_path)
            xml_metadata = xml_parser.metadata
            pdf_path = xml_parser.get_or_extract_pdf()
        elif file_ext == ".pdf":
            xml_candidate = os.path.splitext(file_path)[0] + ".xml"
            if os.path.exists(xml_candidate):
                xml_parser = XMLAppraisalParser(xml_candidate)
                xml_metadata = xml_parser.metadata

        # Fallback to PDF form text extraction if XML fields are missing
        if pdf_path and os.path.exists(pdf_path):
            pdf_form_meta = extract_pdf_form_metrics(pdf_path)
            for k, v in pdf_form_meta.items():
                if xml_metadata.get(f"total_{k}") is None and xml_metadata.get(k) is None:
                    if k == "total_rooms":
                        xml_metadata["total_rooms"] = v
                    elif k == "bedrooms":
                        xml_metadata["total_bedrooms"] = v
                    elif k == "bathrooms":
                        xml_metadata["total_bathrooms"] = v
                    elif k == "gross_living_area":
                        xml_metadata["gross_living_area"] = v

        print(f"[*] Processing Report: {os.path.basename(file_path)}")
        if xml_metadata:
            print(
                f"    Subject: {xml_metadata.get('property_address')}, {xml_metadata.get('city')}"
            )
            print(
                f"    XML Declared: Rooms={xml_metadata.get('total_rooms')}, Beds={xml_metadata.get('total_bedrooms')}, Baths={xml_metadata.get('total_bathrooms')}, GLA={xml_metadata.get('gross_living_area')} sqft"
            )

        # 1 & 2: Photos Analysis
        photo_results = {
            "total_slots_scanned": 0,
            "labeled_photos_count": 0,
            "missing_label_count": 0,
            "bedroom_photos_identified": 0,
            "bathroom_photos_identified": 0,
            "slots": [],
        }
        if run_photos:
            print(
                "[*] Task 1 & 2: Extracting Photos, Identifying Bed/Bath Labels & Checking Missing Labels..."
            )
            photo_results = self.photo_verifier.verify_all_photos(pdf_path, output_dir=output_dir)

        # 3: Blank Pages Detection
        blank_results = []
        blank_pages_list = []
        if run_blank:
            print("[*] Task 3: Scanning for Blank and Low-Content Pages...")
            blank_results = self.blank_detector.detect_blank_pages(pdf_path)
            blank_pages_list = [p for p in blank_results if p["is_blank"]]

        elapsed = round(time.time() - start_time, 2)

        # Summary findings
        summary = {
            "file_name": os.path.basename(file_path),
            "pdf_analyzed": os.path.basename(pdf_path),
            "execution_time_seconds": elapsed,
            "xml_property_metadata": {
                "address": xml_metadata.get("property_address"),
                "city": xml_metadata.get("city"),
                "total_rooms": xml_metadata.get("total_rooms"),
                "bedrooms": xml_metadata.get("total_bedrooms"),
                "bathrooms": xml_metadata.get("total_bathrooms"),
                "gross_living_area": xml_metadata.get("gross_living_area"),
                "appraised_value": xml_metadata.get("appraised_value"),
            },
            "findings": {
                "task1_photo_and_label_inventory": {
                    "total_photo_slots": photo_results["total_slots_scanned"],
                    "labeled_photos_count": photo_results.get(
                        "labeled_photos_count", 0
                    ),
                    "total_room_photos_identified": photo_results.get(
                        "total_room_photos_identified", 0
                    ),
                    "bedroom_photos_identified": photo_results[
                        "bedroom_photos_identified"
                    ],
                    "bathroom_photos_identified": photo_results[
                        "bathroom_photos_identified"
                    ],
                    "photos": [s for s in photo_results["slots"] if s.get("has_image")],
                },
                "task1_photo_identification_and_verification": {
                    "total_photo_slots": photo_results["total_slots_scanned"],
                    "labeled_photos_count": photo_results.get(
                        "labeled_photos_count", 0
                    ),
                    "bedroom_photos_identified": photo_results[
                        "bedroom_photos_identified"
                    ],
                    "bathroom_photos_identified": photo_results[
                        "bathroom_photos_identified"
                    ],
                    "photos": [s for s in photo_results["slots"] if s.get("has_image")],
                },
                "task2_missing_photo_labels": {
                    "missing_label_count": photo_results["missing_label_count"],
                    "missing_labels": [
                        s for s in photo_results["slots"] if s.get("is_missing_label")
                    ],
                },
                "task3_blank_pages": {
                    "total_pages_scanned": len(blank_results),
                    "blank_pages_count": len(blank_pages_list),
                    "blank_pages": blank_pages_list,
                },
            },
        }

        return {
            "summary": summary,
            "photo_details": photo_results,
            "blank_details": blank_results,
        }

    def generate_excel(
        self, report_data: Dict[str, Any], output_path: Optional[str] = None
    ) -> str:
        """
        Exports analysis results to an Excel (.xlsx) report with photo paths.
        """
        if output_path is None:
            file_name = report_data.get("summary", {}).get("file_name", "report")
            base = os.path.splitext(file_name)[0]
            output_path = f"{base}_audit_report.xlsx"
        from .excel_generator import generate_excel_report

        return generate_excel_report(report_data, output_path)
