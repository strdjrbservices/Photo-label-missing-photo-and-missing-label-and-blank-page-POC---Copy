"""
xml_parser.py
Extracts structured property metadata from MISMO 2.6 / 2.6GSE appraisal XML files
and handles base64 embedded PDF extraction.
"""

import xml.etree.ElementTree as ET
import base64
import os
import re
from typing import Dict, Any, Optional, Tuple


def safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    val_str = str(val).replace(",", "").replace("$", "").strip()
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    val_str = str(val).replace(",", "").strip()
    try:
        return int(float(val_str))
    except (ValueError, TypeError):
        return None


class XMLAppraisalParser:
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        self.root = self.tree.getroot()
        self.metadata = self._extract_metadata()

    def _extract_metadata(self) -> Dict[str, Any]:
        data = {
            "file_name": os.path.basename(self.xml_path),
            "mismo_version": self.root.attrib.get("MISMOVersionID", ""),
            "property_address": "",
            "city": "",
            "state": "",
            "postal_code": "",
            "appraiser_name": "",
            "lender_name": "",
            "total_rooms": None,
            "total_bedrooms": None,
            "total_bathrooms": None,
            "gross_living_area": None,
            "appraised_value": None,
            "basement_rr": None,
            "basement_br": None,
            "basement_ba": None,
            "basement_other": None,
            "basement_total_sqft": None,
            "basement_finished_sqft": None,
            "basement_rooms_summary": None,
            "has_embedded_pdf": False,
            "pdf_bytes": None,
        }

        # Traverse tags
        for elem in self.root.iter():
            tag = elem.tag.split("}")[-1]
            attrib = elem.attrib

            # Address & property identification
            if tag == "PROPERTY":
                if attrib.get("_StreetAddress"):
                    data["property_address"] = attrib.get("_StreetAddress")
                if attrib.get("_City"):
                    data["city"] = attrib.get("_City")
                if attrib.get("_State"):
                    data["state"] = attrib.get("_State")
                if attrib.get("_PostalCode"):
                    data["postal_code"] = attrib.get("_PostalCode")

            # Structure information (Rooms, Beds, Baths, GLA)
            if tag == "STRUCTURE":
                if attrib.get("TotalRoomCount"):
                    data["total_rooms"] = safe_int(attrib.get("TotalRoomCount"))
                if attrib.get("TotalBedroomCount"):
                    data["total_bedrooms"] = safe_int(attrib.get("TotalBedroomCount"))
                if attrib.get("TotalBathroomCount"):
                    data["total_bathrooms"] = safe_float(
                        attrib.get("TotalBathroomCount")
                    )
                if attrib.get("GrossLivingAreaSquareFeetCount"):
                    data["gross_living_area"] = safe_float(
                        attrib.get("GrossLivingAreaSquareFeetCount")
                    )

            # Valuation
            if tag == "VALUATION":
                if attrib.get("PropertyAppraisedValueAmount"):
                    data["appraised_value"] = attrib.get("PropertyAppraisedValueAmount")

            # Basement below grade rooms from Sales Grid
            if tag == "COMPARISON_DETAIL":
                if attrib.get("GSEBelowGradeTotalSquareFeetNumber") is not None and data["basement_total_sqft"] is None:
                    data["basement_total_sqft"] = safe_int(attrib.get("GSEBelowGradeTotalSquareFeetNumber"))
                if attrib.get("GSEBelowGradeFinishSquareFeetNumber") is not None and data["basement_finished_sqft"] is None:
                    data["basement_finished_sqft"] = safe_int(attrib.get("GSEBelowGradeFinishSquareFeetNumber"))
                if attrib.get("GSEBelowGradeRecreationRoomCount") is not None and data["basement_rr"] is None:
                    data["basement_rr"] = safe_int(attrib.get("GSEBelowGradeRecreationRoomCount"))
                    data["basement_br"] = safe_int(attrib.get("GSEBelowGradeBedroomRoomCount"))
                    data["basement_ba"] = safe_float(attrib.get("GSEBelowGradeBathroomRoomCount"))
                    data["basement_other"] = safe_int(attrib.get("GSEBelowGradeOtherRoomCount"))
                    if not data["basement_rooms_summary"]:
                        data["basement_rooms_summary"] = f"{data['basement_rr']}rr {data['basement_br']}br {data['basement_ba']}ba {data['basement_other']}o"
            elif tag == "SALE_PRICE_ADJUSTMENT":
                desc = attrib.get("_Description", "")
                m = re.search(r"(\d+)rr\s*(\d+)br\s*([\d\.]+)ba\s*(\d+)o", desc, re.I)
                if m and data["basement_rr"] is None:
                    data["basement_rr"] = safe_int(m.group(1))
                    data["basement_br"] = safe_int(m.group(2))
                    data["basement_ba"] = safe_float(m.group(3))
                    data["basement_other"] = safe_int(m.group(4))
                    data["basement_rooms_summary"] = desc.strip()
                m_sf = re.search(r"(\d+)sf\s*(\d+)sfin", desc, re.I)
                if m_sf:
                    if data["basement_total_sqft"] is None:
                        data["basement_total_sqft"] = safe_int(m_sf.group(1))
                    if data["basement_finished_sqft"] is None:
                        data["basement_finished_sqft"] = safe_int(m_sf.group(2))
            elif tag == "BASEMENT":
                if attrib.get("SquareFeetCount") and data["basement_total_sqft"] is None:
                    data["basement_total_sqft"] = safe_int(attrib.get("SquareFeetCount"))

            # Embedded PDF
            if tag == "DOCUMENT" and elem.text:
                raw_b64 = elem.text.strip()
                if len(raw_b64) > 1000:
                    try:
                        decoded = base64.b64decode(raw_b64)
                        if decoded.startswith(b"%PDF"):
                            data["has_embedded_pdf"] = True
                            data["pdf_bytes"] = decoded
                    except Exception:
                        pass

        return data

    def get_or_extract_pdf(self, output_dir: Optional[str] = None) -> str:
        """
        Returns the path to the corresponding PDF report.
        If a .pdf file exists alongside the .xml, uses it.
        Otherwise extracts the embedded PDF from the XML.
        """
        base_no_ext = os.path.splitext(self.xml_path)[0]
        pdf_candidate = base_no_ext + ".pdf"
        if os.path.exists(pdf_candidate):
            return pdf_candidate

        if self.metadata["has_embedded_pdf"] and self.metadata["pdf_bytes"]:
            out_folder = output_dir or os.path.dirname(self.xml_path) or "."
            extracted_path = os.path.join(
                out_folder, f"{os.path.basename(base_no_ext)}_extracted.pdf"
            )
            with open(extracted_path, "wb") as f:
                f.write(self.metadata["pdf_bytes"])
            return extracted_path

        raise FileNotFoundError(
            f"No PDF companion found and no embedded PDF in {self.xml_path}"
        )
