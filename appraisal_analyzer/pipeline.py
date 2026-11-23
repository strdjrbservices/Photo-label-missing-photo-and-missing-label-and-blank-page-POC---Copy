"""
pipeline.py
Main orchestrator that executes appraisal verification tasks:
1. Extract photos and labels, and identify bedroom & bathroom photos.
2. Detect missing labels for photos.
3. Detect blank pages.
Supports both .XML (MISMO 2.6 with embedded PDF) and direct .PDF appraisal reports.
"""

import os
import json
import time
import re
from typing import Dict, Any, Optional

import pymupdf

from .xml_parser import XMLAppraisalParser
from .photo_verifier import PhotoVerifier
from .blank_detector import BlankPageDetector


def extract_pdf_form_metrics(pdf_path: str) -> dict:
    """Extracts appraisal property metadata, finished area room counts, and basement metrics directly from PDF form text."""
    metrics = {
        'property_address': None,
        'city': None,
        'state': None,
        'zip_code': None,
        'appraised_value': None,
        'total_rooms': None,
        'bedrooms': None,
        'bathrooms': None,
        'gross_living_area': None,
        'basement_rr': None,
        'basement_br': None,
        'basement_ba': None,
        'basement_other': None,
        'basement_total_sqft': None,
        'basement_finished_sqft': None,
        'basement_rooms_summary': None
    }
    doc = None
    try:
        doc = pymupdf.open(pdf_path)
        for p_idx in range(min(10, len(doc))):
            page = doc[p_idx]
            text = page.get_text()
            words = page.get_text("words")

            # 1. Property Address, City, State, Zip from URAR page header
            if not metrics['property_address']:
                p_word = None
                for idx, w in enumerate(words):
                    if w[4].lower() == 'property' and idx + 1 < len(words) and words[idx+1][4].lower().startswith('address'):
                        p_word = w
                        break
                if p_word:
                    py = p_word[1]
                    line_words = [w for w in words if abs(w[1] - py) <= 7]
                    line_words.sort(key=lambda w: w[0])
                    
                    addr_tokens = []
                    city_tokens = []
                    state_tokens = []
                    zip_tokens = []
                    
                    for w in line_words:
                        val = w[4].strip()
                        if val.lower() in ['property', 'address', 'city', 'state', 'zip', 'code', 'file', 'no.', 'no']:
                            continue
                        wx = w[0]
                        if 70 <= wx < 290:
                            addr_tokens.append(val)
                        elif 290 <= wx < 450:
                            city_tokens.append(val)
                        elif 450 <= wx < 500:
                            state_tokens.append(val)
                        elif 500 <= wx <= 585:
                            zip_tokens.append(val)

                    if addr_tokens:
                        metrics['property_address'] = " ".join(addr_tokens).strip()
                    if city_tokens:
                        metrics['city'] = " ".join(city_tokens).strip()
                    if state_tokens:
                        metrics['state'] = " ".join(state_tokens).strip()
                    if zip_tokens:
                        metrics['zip_code'] = " ".join(zip_tokens).strip()

            # 2. Finished Area Above Grade: Total Rooms, Bedrooms, Bathrooms, GLA
            if "finished area above grade contains" in text.lower():
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
                        if wl in ["rooms", "rooms:"] and idx > 0 and lw[idx - 1][4].replace(",", "").isdigit():
                            metrics["total_rooms"] = int(lw[idx - 1][4].replace(",", ""))
                        elif "bedroom" in wl and idx > 0 and lw[idx - 1][4].replace(",", "").isdigit():
                            metrics["bedrooms"] = int(lw[idx - 1][4].replace(",", ""))
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

            # 3. Sales Comparison Subject Column Extraction for Basement & Room Counts
            if "sales comparison approach" in text.lower() or "value adjustments" in text.lower():
                # Scope basement row precisely to the Basement row label on the left (x < 85)
                b_labels = [w for w in words if w[4].lower().startswith("basement") and w[0] < 85]
                if not b_labels:
                    b_labels = [w for w in words if "basement" in w[4].lower() and w[0] < 85]
                if b_labels:
                    by = b_labels[0][1]
                    # Subject column words on this specific row
                    row_words = [w for w in words if 88 <= w[0] <= 190 and -5 <= (w[1] - by) <= 25]
                    row_words.sort(key=lambda w: (w[1], w[0]))
                    row_txt = " ".join(w[4] for w in row_words)

                    # Below Grade UAD counts (rr, br, ba, o)
                    m_uad = re.search(r"(\d+)\s*rr\s*(\d+)\s*br\s*([\d\.]+)\s*ba\s*(\d+)\s*o", row_txt, re.I)
                    if m_uad and metrics["basement_rr"] is None:
                        metrics["basement_rr"] = int(m_uad.group(1))
                        metrics["basement_br"] = int(m_uad.group(2))
                        try:
                            metrics["basement_ba"] = float(m_uad.group(3))
                        except ValueError:
                            metrics["basement_ba"] = 0.0
                        metrics["basement_other"] = int(m_uad.group(4))
                        metrics["basement_rooms_summary"] = f"{m_uad.group(1)}rr {m_uad.group(2)}br {m_uad.group(3)}ba {m_uad.group(4)}o"

                    # Check for 0sf or 0 sf (no basement or 0 finished)
                    if re.search(r"\b0\s*sf\b", row_txt, re.I) and metrics["basement_total_sqft"] is None:
                        metrics["basement_total_sqft"] = 0
                        metrics["basement_finished_sqft"] = 0
                        if not metrics["basement_rooms_summary"]:
                            metrics["basement_rooms_summary"] = "0sf (None)"
                    else:
                        m_sf = re.search(r"(\d+)\s*sf\s*(\d+)\s*s?f?(?:in|wo|wu)?", row_txt, re.I)
                        if m_sf and metrics["basement_total_sqft"] is None:
                            metrics["basement_total_sqft"] = int(m_sf.group(1))
                            metrics["basement_finished_sqft"] = int(m_sf.group(2))
                        elif metrics["basement_total_sqft"] is None:
                            m_sf1 = re.search(r"(\d+)\s*sf", row_txt, re.I)
                            if m_sf1:
                                metrics["basement_total_sqft"] = int(m_sf1.group(1))

                # Subject column fallback room counts from subject column if not found earlier
                subj_words = [w for w in words if 90 <= w[0] <= 188]
                subj_text = " ".join(w[4] for w in sorted(subj_words, key=lambda w: (w[1], w[0])))
                if metrics["total_rooms"] is None or metrics["bedrooms"] is None or metrics["gross_living_area"] is None:
                    m_rc = re.search(r"Total\s+Bdrms\.?\s+Baths\s+(\d+)\s+(\d+)\s+([\d\.]+)", subj_text, re.I)
                    if m_rc:
                        metrics["total_rooms"] = int(m_rc.group(1))
                        metrics["bedrooms"] = int(m_rc.group(2))
                        metrics["bathrooms"] = float(m_rc.group(3))
                    m_gla = re.search(r"([\d,]+)\s*sq\.?\s*ft", subj_text, re.I)
                    if m_gla and metrics["gross_living_area"] is None:
                        try:
                            metrics["gross_living_area"] = float(m_gla.group(1).replace(",", ""))
                        except Exception:
                            pass

        # 4. Appraised Value extraction across document
        target_val_keywords = [
            "appraised value of subject property",
            "opinion of value",
            "appraised value:",
            "indicated value by sales comparison approach",
            "opinion of the market value",
            "effective date of this appraisal is",
            "market value"
        ]
        for p_idx in range(min(16, len(doc))):
            lines = [l.strip() for l in doc[p_idx].get_text().splitlines() if l.strip()]
            for idx, line in enumerate(lines):
                line_lower = line.lower()
                for kw in target_val_keywords:
                    if kw in line_lower:
                        m_same = re.search(r'\$?\s*([0-9]{2,3}(?:,[0-9]{3})+)', line)
                        if m_same and int(m_same.group(1).replace(',', '')) >= 20000:
                            metrics['appraised_value'] = m_same.group(1).replace(',', '')
                            break
                        for next_idx in range(idx + 1, min(len(lines), idx + 4)):
                            m_next = re.search(r'^\$?\s*([0-9]{2,3}(?:,[0-9]{3})+)$', lines[next_idx])
                            if m_next and int(m_next.group(1).replace(',', '')) >= 20000:
                                metrics['appraised_value'] = m_next.group(1).replace(',', '')
                                break
                        if metrics['appraised_value']:
                            break
                        for prev_idx in range(max(0, idx - 3), idx):
                            m_prev = re.search(r'^\$?\s*([0-9]{2,3}(?:,[0-9]{3})+)$', lines[prev_idx])
                            if m_prev and int(m_prev.group(1).replace(',', '')) >= 20000:
                                metrics['appraised_value'] = m_prev.group(1).replace(',', '')
                                break
                    if metrics['appraised_value']:
                        break
                if metrics['appraised_value']:
                    break
            if metrics['appraised_value']:
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

        # Extract or fallback to PDF form text extraction
        if pdf_path and os.path.exists(pdf_path):
            pdf_form_meta = extract_pdf_form_metrics(pdf_path)
            for k, v in pdf_form_meta.items():
                if v is not None:
                    if xml_metadata.get(k) is None:
                        xml_metadata[k] = v
                    if k == "property_address" and not xml_metadata.get("property_address"):
                        xml_metadata["property_address"] = v
                    elif k == "city" and not xml_metadata.get("city"):
                        xml_metadata["city"] = v
                    elif k == "appraised_value" and not xml_metadata.get("appraised_value"):
                        xml_metadata["appraised_value"] = v
                    elif k == "total_rooms" and not xml_metadata.get("total_rooms"):
                        xml_metadata["total_rooms"] = v
                    elif k == "bedrooms" and not xml_metadata.get("total_bedrooms"):
                        xml_metadata["total_bedrooms"] = v
                    elif k == "bathrooms" and not xml_metadata.get("total_bathrooms"):
                        xml_metadata["total_bathrooms"] = v
                    elif k == "gross_living_area" and not xml_metadata.get("gross_living_area"):
                        xml_metadata["gross_living_area"] = v
                    elif k.startswith("basement_") and xml_metadata.get(k) is None:
                        xml_metadata[k] = v

        print(f"[*] Processing Report: {os.path.basename(file_path)}")
        if xml_metadata:
            print(
                f"    Subject: {xml_metadata.get('property_address')}, {xml_metadata.get('city')}"
            )
            print(
                f"    Declared: Rooms={xml_metadata.get('total_rooms')}, Beds={xml_metadata.get('total_bedrooms') or xml_metadata.get('bedrooms')}, Baths={xml_metadata.get('total_bathrooms') or xml_metadata.get('bathrooms')}, GLA={xml_metadata.get('gross_living_area')} sqft"
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
                "address": xml_metadata.get("property_address") or xml_metadata.get("address"),
                "city": xml_metadata.get("city"),
                "state": xml_metadata.get("state"),
                "zip_code": xml_metadata.get("zip_code"),
                "total_rooms": xml_metadata.get("total_rooms"),
                "bedrooms": xml_metadata.get("total_bedrooms") or xml_metadata.get("bedrooms"),
                "bathrooms": xml_metadata.get("total_bathrooms") or xml_metadata.get("bathrooms"),
                "gross_living_area": xml_metadata.get("gross_living_area"),
                "appraised_value": xml_metadata.get("appraised_value"),
                "basement_rr": xml_metadata.get("basement_rr"),
                "basement_br": xml_metadata.get("basement_br"),
                "basement_ba": xml_metadata.get("basement_ba"),
                "basement_other": xml_metadata.get("basement_other"),
                "basement_total_sqft": xml_metadata.get("basement_total_sqft"),
                "basement_finished_sqft": xml_metadata.get("basement_finished_sqft"),
                "basement_rooms_summary": xml_metadata.get("basement_rooms_summary"),
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
