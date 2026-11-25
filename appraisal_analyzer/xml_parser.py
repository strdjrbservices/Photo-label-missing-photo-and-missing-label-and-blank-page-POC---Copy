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
            "sections": {
                "improvements": {
                    "gla": None,
                    "rooms": None,
                    "bedrooms": None,
                    "bathrooms": None,
                    "basement_sqft": None,
                    "basement_finished_sqft": None,
                },
                "sales_grid": {
                    "gla": None,
                    "rooms": None,
                    "bedrooms": None,
                    "bathrooms": None,
                },
            },
        }

        def _walk(elem: ET.Element, in_comp: bool = False):
            tag = elem.tag.split("}")[-1]
            attrib = elem.attrib

            # Track whether this subtree belongs to a Comparable Sale (non-Subject)
            curr_in_comp = in_comp
            if tag == "COMPARABLE_SALE":
                seq = (
                    attrib.get("PropertySequenceIdentifier")
                    or attrib.get("ComparableSaleSequenceID")
                    or attrib.get("_SequenceIdentifier")
                    or ""
                ).strip()
                # Sequence "0" (or "Subject") is the Subject column; "1", "2", ... are Comps
                if seq and seq.lower() not in ("0", "subject"):
                    curr_in_comp = True

            if not curr_in_comp:
                # Subject column directly on COMPARABLE_SALE seq="0" or ROOM_ADJUSTMENT
                if tag in ("COMPARABLE_SALE", "ROOM_ADJUSTMENT"):
                    if attrib.get("TotalRoomCount") is not None and data["sections"]["sales_grid"]["rooms"] is None:
                        data["sections"]["sales_grid"]["rooms"] = safe_int(attrib.get("TotalRoomCount"))
                    if attrib.get("TotalBedroomCount") is not None and data["sections"]["sales_grid"]["bedrooms"] is None:
                        data["sections"]["sales_grid"]["bedrooms"] = safe_int(attrib.get("TotalBedroomCount"))
                    if attrib.get("TotalBathroomCount") is not None and data["sections"]["sales_grid"]["bathrooms"] is None:
                        data["sections"]["sales_grid"]["bathrooms"] = safe_float(attrib.get("TotalBathroomCount"))
                    sg_gla = (
                        attrib.get("GrossLivingAreaSquareFeetCount")
                        or attrib.get("GrossBuildingAreaSquareFeetCount")
                    )
                    if sg_gla is not None and data["sections"]["sales_grid"]["gla"] is None:
                        data["sections"]["sales_grid"]["gla"] = safe_float(sg_gla)

                # Address & property identification (Subject only)
                if tag == "PROPERTY":
                    if attrib.get("_StreetAddress") and not data["property_address"]:
                        data["property_address"] = attrib.get("_StreetAddress")
                    if attrib.get("_City") and not data["city"]:
                        data["city"] = attrib.get("_City")
                    if attrib.get("_State") and not data["state"]:
                        data["state"] = attrib.get("_State")
                    if attrib.get("_PostalCode") and not data["postal_code"]:
                        data["postal_code"] = attrib.get("_PostalCode")

                # Structure information (Improvements Section: Subject Rooms, Beds, Baths, GLA/GBA)
                if tag == "STRUCTURE":
                    if attrib.get("TotalRoomCount") is not None and data["total_rooms"] is None:
                        data["total_rooms"] = safe_int(attrib.get("TotalRoomCount"))
                        data["sections"]["improvements"]["rooms"] = data["total_rooms"]
                    if attrib.get("TotalBedroomCount") is not None and data["total_bedrooms"] is None:
                        data["total_bedrooms"] = safe_int(attrib.get("TotalBedroomCount"))
                        data["sections"]["improvements"]["bedrooms"] = data["total_bedrooms"]
                    if attrib.get("TotalBathroomCount") is not None and data["total_bathrooms"] is None:
                        data["total_bathrooms"] = safe_float(attrib.get("TotalBathroomCount"))
                        data["sections"]["improvements"]["bathrooms"] = data["total_bathrooms"]
                    gla_attr = (
                        attrib.get("GrossLivingAreaSquareFeetCount")
                        or attrib.get("GrossBuildingAreaSquareFeetCount")
                        or attrib.get("TotalGrossBuildingAreaSquareFeetCount")
                    )
                    if gla_attr is not None and data["gross_living_area"] is None:
                        data["gross_living_area"] = safe_float(gla_attr)
                        data["sections"]["improvements"]["gla"] = data["gross_living_area"]

                # Valuation (Subject only)
                if tag == "VALUATION":
                    if attrib.get("PropertyAppraisedValueAmount") and not data["appraised_value"]:
                        data["appraised_value"] = attrib.get("PropertyAppraisedValueAmount")

                # Basement below grade & Sales Grid values from Subject column
                if tag == "COMPARISON_DETAIL":
                    r_cnt = attrib.get("GSEAboveGradeTotalRoomCount") or attrib.get("TotalRoomCount")
                    b_cnt = attrib.get("GSEAboveGradeBedroomCount") or attrib.get("TotalBedroomCount")
                    ba_cnt = attrib.get("GSEAboveGradeBathroomCount") or attrib.get("TotalBathroomCount")
                    if r_cnt is not None and data["sections"]["sales_grid"]["rooms"] is None:
                        data["sections"]["sales_grid"]["rooms"] = safe_int(r_cnt)
                    if b_cnt is not None and data["sections"]["sales_grid"]["bedrooms"] is None:
                        data["sections"]["sales_grid"]["bedrooms"] = safe_int(b_cnt)
                    if ba_cnt is not None and data["sections"]["sales_grid"]["bathrooms"] is None:
                        data["sections"]["sales_grid"]["bathrooms"] = safe_float(ba_cnt)
                    grid_gla_attr = (
                        attrib.get("GSEGrossLivingAreaSquareFeetNumber")
                        or attrib.get("GSEGrossBuildingAreaSquareFeetNumber")
                    )
                    if grid_gla_attr is not None and data["sections"]["sales_grid"]["gla"] is None:
                        data["sections"]["sales_grid"]["gla"] = safe_float(grid_gla_attr)
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
                    adj_type = (attrib.get("_Type") or "").lower()
                    desc = attrib.get("_Description", "")
                    if "grosslivingarea" in adj_type or "grossbuildingarea" in adj_type:
                        m_gla_adj = re.search(r"([\d,]+)", desc)
                        if m_gla_adj and data["sections"]["sales_grid"]["gla"] is None:
                            val = safe_float(m_gla_adj.group(1))
                            if val and val >= 150:
                                data["sections"]["sales_grid"]["gla"] = val
                    is_basement_adj = (not adj_type) or ("basement" in adj_type) or ("belowgrade" in adj_type)
                    if is_basement_adj:
                        m = re.search(r"(\d+)\s*rr\s*(\d+)\s*br\s*([\d\.]+)\s*ba\s*(\d+)\s*o", desc, re.I)
                        if m and data["basement_rr"] is None:
                            data["basement_rr"] = safe_int(m.group(1))
                            data["basement_br"] = safe_int(m.group(2))
                            data["basement_ba"] = safe_float(m.group(3))
                            data["basement_other"] = safe_int(m.group(4))
                            data["basement_rooms_summary"] = desc.strip()
                        m_sf = re.search(r"(\d+)\s*sf\s*(\d+)\s*s?f?(?:in|wo|wu)?", desc, re.I)
                        if m_sf:
                            if data["basement_total_sqft"] is None:
                                data["basement_total_sqft"] = safe_int(m_sf.group(1))
                            if data["basement_finished_sqft"] is None:
                                data["basement_finished_sqft"] = safe_int(m_sf.group(2))
                        elif re.search(r"\b0\s*sf\b", desc, re.I) and data["basement_total_sqft"] is None:
                            data["basement_total_sqft"] = 0
                            data["basement_finished_sqft"] = 0
                            if not data["basement_rooms_summary"]:
                                data["basement_rooms_summary"] = desc.strip() or "0sf"
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

            for child in elem:
                _walk(child, curr_in_comp)

        _walk(self.root, in_comp=False)

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
