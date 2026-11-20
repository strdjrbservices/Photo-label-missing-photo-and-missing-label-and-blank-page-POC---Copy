"""
excel_generator.py
Generates comprehensive Excel (.xlsx) audit reports for appraisal analyses,
including photo inventories, extracted photo paths with clickable hyperlinks,
missing label detections, and blank page findings.
"""

import os
import re
from typing import Dict, Any, List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


class ExcelReportGenerator:
    def __init__(self):
        # Color palette
        self.header_fill = PatternFill(
            start_color="1F4E78", end_color="1F4E78", fill_type="solid"
        )  # Navy
        self.section_fill = PatternFill(
            start_color="2F5597", end_color="2F5597", fill_type="solid"
        )  # Slate
        self.subheader_fill = PatternFill(
            start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
        )

        self.title_font = Font(name="Segoe UI", size=14, bold=True, color="1F4E78")
        self.header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        self.bold_font = Font(name="Segoe UI", size=10, bold=True)
        self.data_font = Font(name="Segoe UI", size=10)
        self.link_font = Font(
            name="Segoe UI", size=10, color="0563C1", underline="single"
        )

        # Borders
        thin_side = Side(border_style="thin", color="D9D9D9")
        self.thin_border = Border(
            left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
        )

        # Status highlight fills
        self.status_fills = {
            "LABELED": PatternFill(
                start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"
            ),
            "VALID": PatternFill(
                start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"
            ),
            "MISSING_LABEL": PatternFill(
                start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"
            ),
            "MISSING_PHOTO": PatternFill(
                start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"
            ),
            "EMPTY_SLOT": PatternFill(
                start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"
            ),
        }

    def generate(self, report_data: Dict[str, Any], output_path: str) -> str:
        """
        Creates a multi-tab Excel workbook from the analysis report dictionary.
        """
        wb = openpyxl.Workbook()

        # Sheet 1: Summary Overview
        ws_summary = wb.active
        ws_summary.title = "Report Summary"
        self._build_summary_sheet(ws_summary, report_data)

        # Sheet 2: Photos & Labels
        ws_photos = wb.create_sheet(title="Photos & Labels")
        self._build_photos_sheet(ws_photos, report_data)

        # Sheet 3: Blank Pages
        ws_blanks = wb.create_sheet(title="Blank Pages")
        self._build_blanks_sheet(ws_blanks, report_data)

        # Auto-adjust column widths on all worksheets
        for sheet in wb.worksheets:
            sheet.views.sheetView[0].showGridLines = True
            for col in sheet.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val_str = str(cell.value or "")
                    if "\n" in val_str:
                        val_str = max(val_str.split("\n"), key=len)
                    max_len = max(max_len, len(val_str))
                sheet.column_dimensions[col_letter].width = min(
                    max(max_len + 3, 12), 70
                )

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        try:
            wb.save(output_path)
            return output_path
        except PermissionError:
            # File is open in Microsoft Excel or another viewer
            base, ext = os.path.splitext(output_path)
            alt_path = f"{base}_new{ext}"
            wb.save(alt_path)
            print(
                f"[!] Note: '{os.path.basename(output_path)}' is locked/open in Excel. Saved updated report to '{os.path.basename(alt_path)}'."
            )
            return alt_path

    def _build_summary_sheet(self, ws, report_data: Dict[str, Any]):
        summary = report_data.get("summary", {})
        findings = summary.get("findings", {})
        xml_meta = summary.get("xml_property_metadata", {})
        p_task = findings.get("task1_photo_and_label_inventory") or findings.get(
            "task1_photo_identification_and_verification", {}
        )
        m_task = findings.get("task2_missing_photo_labels", {})
        b_task = findings.get("task3_blank_pages", {})

        # Title Block
        ws.cell(
            row=1, column=1, value="APPRAISAL QUALITY CONTROL & PHOTO AUDIT REPORT"
        ).font = self.title_font
        ws.merge_cells("A1:D1")

        # Meta info
        meta_rows = [
            ("Report File", summary.get("file_name", "N/A")),
            ("Companion PDF", summary.get("pdf_analyzed", "N/A")),
            (
                "Analysis Duration",
                f"{summary.get('execution_time_seconds', 0)} seconds",
            ),
            ("Subject Address", xml_meta.get("address", "N/A")),
            ("City / State", xml_meta.get("city", "N/A")),
            ("XML Declared Total Rooms", xml_meta.get("total_rooms", "N/A")),
            ("XML Declared Bedrooms", xml_meta.get("bedrooms", "N/A")),
            ("XML Declared Bathrooms", xml_meta.get("bathrooms", "N/A")),
            (
                "XML Gross Living Area (GLA)",
                f"{xml_meta.get('gross_living_area', 'N/A')} sqft",
            ),
            ("XML Appraised Value", xml_meta.get("appraised_value", "N/A")),
        ]

        curr_row = 3
        ws.cell(row=curr_row, column=1, value="Report & Property Metadata").font = (
            self.header_font
        )
        ws.cell(row=curr_row, column=1).fill = self.section_fill
        ws.merge_cells(
            start_row=curr_row, start_column=1, end_row=curr_row, end_column=2
        )
        curr_row += 1

        for label, val in meta_rows:
            c1 = ws.cell(row=curr_row, column=1, value=label)
            c2 = ws.cell(row=curr_row, column=2, value=val)
            c1.font = self.bold_font
            c2.font = self.data_font
            c1.border = self.thin_border
            c2.border = self.thin_border
            curr_row += 1

        # Summary Findings Audit Table
        curr_row += 1
        ws.cell(row=curr_row, column=1, value="Audit Findings Summary").font = (
            self.header_font
        )
        ws.cell(row=curr_row, column=1).fill = self.section_fill
        ws.merge_cells(
            start_row=curr_row, start_column=1, end_row=curr_row, end_column=2
        )
        curr_row += 1

        finding_rows = [
            ("Total Photo Slots Scanned", p_task.get("total_photo_slots", 0)),
            ("Photos with Attached Labels", p_task.get("labeled_photos_count", 0)),
            ("Photos Missing Labels", m_task.get("missing_label_count", 0)),
            (
                "Total Rooms Identified in Photo Labels",
                p_task.get("total_room_photos_identified", p_task.get("bedroom_photos_identified", 0)),
            ),
            (
                "Bedrooms Identified in Photo Labels",
                p_task.get("bedroom_photos_identified", 0),
            ),
            (
                "Bathrooms Identified in Photo Labels",
                p_task.get("bathroom_photos_identified", 0),
            ),
            ("Blank Pages Detected", b_task.get("blank_pages_count", 0)),
        ]

        for label, val in finding_rows:
            c1 = ws.cell(row=curr_row, column=1, value=label)
            c2 = ws.cell(row=curr_row, column=2, value=val)
            c1.font = self.bold_font
            c2.font = self.data_font
            c1.border = self.thin_border
            c2.border = self.thin_border

            # Highlight missing labels
            if label == "Photos Missing Labels" and val > 0:
                c2.fill = self.status_fills["MISSING_LABEL"]
                c2.font = self.bold_font
            curr_row += 1

    def _build_photos_sheet(self, ws, report_data: Dict[str, Any]):
        slots = report_data.get("photo_details", {}).get("slots", [])
        if not slots:
            findings = report_data.get("summary", {}).get("findings", {})
            p_task = findings.get("task1_photo_and_label_inventory") or findings.get(
                "task1_photo_identification_and_verification", {}
            )
            slots = p_task.get("photos", [])

        headers = [
            "Page #",
            "Slot Name",
            "Photo Attached?",
            "Photo Label",
            "Normalized Category",
            "Status",
            "Photo File Path",
            "Dimensions (WxH)",
            "File Size (KB)",
            "Blur Score",
            "Brightness",
            "Is Blurry?",
            "Note",
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            cell.border = self.thin_border
        ws.row_dimensions[1].height = 26

        curr_row = 2
        for s in slots:
            has_image = s.get("has_image", False)
            img_info = s.get("image_info") or {}
            img_qual = s.get("image_quality") or {}
            photo_path = s.get("photo_path")
            status = s.get("status", "VALID")

            dim_str = (
                f"{img_qual.get('width', img_info.get('width', ''))}x{img_qual.get('height', img_info.get('height', ''))}"
                if has_image
                else ""
            )
            size_kb = (
                round(img_info.get("size", 0) / 1024, 1) if img_info.get("size") else ""
            )
            blur_val = img_qual.get("blur_score", "")
            bright_val = img_qual.get("brightness", "")
            is_blurry_str = (
                "Yes" if img_qual.get("is_blurry") else ("No" if img_qual else "")
            )

            row_values = [
                s.get("page_number", ""),
                s.get("slot_name", ""),
                "Yes" if has_image else "No",
                s.get("raw_label", ""),
                s.get("normalized_label", ""),
                status,
                photo_path or "",
                dim_str,
                size_kb,
                blur_val,
                bright_val,
                is_blurry_str,
                s.get("verification_note", ""),
            ]

            for col_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=curr_row, column=col_idx, value=val)
                cell.font = self.data_font
                cell.border = self.thin_border
                cell.alignment = Alignment(vertical="center")

                # Align numbers/centers
                if col_idx in [1, 3, 6, 8, 9, 10, 11, 12]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                # Hyperlink photo path
                if col_idx == 7 and val and os.path.exists(str(val)):
                    cell.hyperlink = (
                        f"file:///{os.path.abspath(str(val)).replace(os.sep, '/')}"
                    )
                    cell.font = self.link_font
                    cell.value = os.path.basename(str(val))

                # Status color highlight
                if col_idx == 6:
                    fill = self.status_fills.get(status)
                    if fill:
                        cell.fill = fill
                    if status in ["MISSING_LABEL", "MISSING_PHOTO"]:
                        cell.font = self.bold_font

            ws.row_dimensions[curr_row].height = 20
            curr_row += 1

    def _build_blanks_sheet(self, ws, report_data: Dict[str, Any]):
        blank_details = report_data.get("blank_details", [])
        headers = [
            "Page #",
            "Classification",
            "Is Blank?",
            "Content %",
            "Edge Density %",
            "Blur Variance",
            "Details",
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = self.thin_border
        ws.row_dimensions[1].height = 26

        curr_row = 2
        for b in blank_details:
            is_blank = b.get("is_blank", False)
            row_values = [
                b.get("page_number", ""),
                b.get("classification", ""),
                "Yes" if is_blank else "No",
                f"{b.get('content_pixel_pct', 0):.2f}%",
                f"{b.get('edge_density_pct', 0):.2f}%",
                round(b.get("blur_variance", 0), 1),
                b.get("reason", ""),
            ]

            for col_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=curr_row, column=col_idx, value=val)
                cell.font = self.data_font
                cell.border = self.thin_border
                cell.alignment = Alignment(vertical="center")

                if col_idx in [1, 3, 4, 5, 6]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                if col_idx == 3 and is_blank:
                    cell.fill = self.status_fills["MISSING_LABEL"]
                    cell.font = self.bold_font

            ws.row_dimensions[curr_row].height = 20
            curr_row += 1


def generate_excel_report(report_data: Dict[str, Any], output_path: str) -> str:
    """
    Convenience function to generate an Excel report.
    """
    generator = ExcelReportGenerator()
    return generator.generate(report_data, output_path)
