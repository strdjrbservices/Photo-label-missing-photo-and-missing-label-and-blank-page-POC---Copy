import os
import tempfile
import pymupdf
from django.test import TestCase, Client
from django.urls import reverse
from appraisal_analyzer.xml_parser import XMLAppraisalParser
from appraisal_analyzer.pipeline import extract_pdf_form_metrics
from .models import ReportAudit, AuditPhotoSlot


class GroupPhotoFilteringTests(TestCase):
    def setUp(self):
        self.audit = ReportAudit.objects.create(
            file_name="test_report.xml",
            status="COMPLETED",
            total_rooms=10,
            total_bedrooms=6,
            total_bathrooms=1.0,
        )
        slots = [
            (14, "Photo 1", "FRONT VIEW OF", "Exterior Front"),
            (14, "Photo 2", "REAR VIEW OF", "Exterior Rear"),
            (14, "Photo 3", "STREET SCENE", "Street View"),
            (15, "Photo 1", "Unit #1 Kitchen", "Kitchen"),
            (15, "Photo 2", "Unit #1 Full bathroom", "Bathroom"),
            (15, "Photo 3", "Unit #1 Living room", "Living Room"),
            (16, "Photo 1", "Solarium", "Solarium"),
            (16, "Photo 2", "Mudroom", "Mudroom"),
            (16, "Photo 3", "Mud Room", "Mudroom"),
            (17, "Photo 2", "UNIT #1 BEDROOM", "Bedroom"),
            (18, "Photo 1", "THREE CAR GARAGE", "Garage"),
            (18, "Photo 2", "Garage Interior", "Garage"),
            (22, "Photo 1", "BASEMENT KITCHEN", "Kitchen"),
            (22, "Photo 2", "BASEMENT REC ROOM", "Basement"),
            (22, "Photo 3", "BASEMENT FULL BATHROOM", "Bathroom"),
            (23, "Photo 1", "COMPARABLE SALE #1", "Comparable"),
        ]
        for page, name, raw_lbl, norm_lbl in slots:
            AuditPhotoSlot.objects.create(
                report=self.audit,
                page_number=page,
                slot_name=name,
                raw_label=raw_lbl,
                normalized_label=norm_lbl,
                status="LABELED",
                has_image=True,
            )

    def test_total_rooms_group_includes_subject_front_rear_street(self):
        resp = self.client.get(reverse("audit_detail", args=[self.audit.id]))
        self.assertEqual(resp.status_code, 200)
        total_room_photos = resp.context["total_room_photos"]
        labels = [s.raw_label for s in total_room_photos]
        self.assertIn("FRONT VIEW OF", labels)
        self.assertIn("REAR VIEW OF", labels)
        self.assertIn("STREET SCENE", labels)
        self.assertIn("Unit #1 Kitchen", labels)
        self.assertIn("Unit #1 Living room", labels)
        self.assertIn("Solarium", labels)
        self.assertIn("Mudroom", labels)
        self.assertIn("Mud Room", labels)
        self.assertIn("BASEMENT KITCHEN", labels)
        # Solarium & Mudroom/Mud Room count toward room_photos_identified (3 kitchens/living + 3 solarium/mudroom + 1 bedroom = 7)
        self.assertEqual(self.audit.room_photos_identified, 7)
        # Excluded groups
        self.assertNotIn("UNIT #1 BEDROOM", labels)
        self.assertNotIn("Unit #1 Full bathroom", labels)
        self.assertNotIn("BASEMENT REC ROOM", labels)
        self.assertNotIn("BASEMENT FULL BATHROOM", labels)
        self.assertNotIn("COMPARABLE SALE #1", labels)
        # Garage photos group & audit card link
        garage_photos = resp.context["garage_photos"]
        self.assertEqual([s.raw_label for s in garage_photos], ["THREE CAR GARAGE", "Garage Interior"])
        self.assertContains(resp, "Garage Photos:")
        self.assertContains(resp, "showGroupPhotos('garage', 'Garage')")


class SubjectColumnBasementExtractionTests(TestCase):
    def test_xml_ignores_comparable_basement_when_subject_has_no_basement(self):
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<VALUATION_RESPONSE MISMOVersionID="2.6GSE">
  <VALUATION_METHODS>
    <SALES_COMPARISON>
      <COMPARABLE_SALE PropertySequenceIdentifier="1">
        <SALE_PRICE_ADJUSTMENT _Type="BasementAndFinishedRoomsBelowGrade" _Description="1rr0br1.0ba1o" />
        <COMPARISON_DETAIL GSEBelowGradeTotalSquareFeetNumber="1013" GSEBelowGradeFinishSquareFeetNumber="800" GSEBelowGradeRecreationRoomCount="1" GSEBelowGradeBedroomRoomCount="0" GSEBelowGradeBathroomRoomCount="1.0" GSEBelowGradeOtherRoomCount="1" />
      </COMPARABLE_SALE>
      <COMPARABLE_SALE PropertySequenceIdentifier="0">
        <SALE_PRICE_ADJUSTMENT _Type="BasementAndFinishedRoomsBelowGrade" _Description="0sf" />
      </COMPARABLE_SALE>
      <COMPARABLE_SALE PropertySequenceIdentifier="2">
        <SALE_PRICE_ADJUSTMENT _Type="BasementAndFinishedRoomsBelowGrade" _Description="2rr1br1.0ba0o" />
      </COMPARABLE_SALE>
    </SALES_COMPARISON>
  </VALUATION_METHODS>
</VALUATION_RESPONSE>"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
            tmp.write(xml_content)
            tmp_path = tmp.name
        try:
            parser = XMLAppraisalParser(tmp_path)
            self.assertIsNone(parser.metadata["basement_rr"])
            self.assertIsNone(parser.metadata["basement_br"])
            self.assertIsNone(parser.metadata["basement_ba"])
            self.assertIsNone(parser.metadata["basement_other"])
            self.assertEqual(parser.metadata["basement_total_sqft"], 0)
        finally:
            os.remove(tmp_path)

    def test_xml_captures_subject_basement_only(self):
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<VALUATION_RESPONSE MISMOVersionID="2.6GSE">
  <VALUATION_METHODS>
    <SALES_COMPARISON>
      <COMPARABLE_SALE PropertySequenceIdentifier="1">
        <SALE_PRICE_ADJUSTMENT _Type="BasementAndFinishedRoomsBelowGrade" _Description="1rr0br1.0ba1o" />
      </COMPARABLE_SALE>
      <COMPARABLE_SALE PropertySequenceIdentifier="0">
        <SALE_PRICE_ADJUSTMENT _Type="BasementAndFinishedRoomsBelowGrade" _Description="2rr1br1.5ba0o" />
      </COMPARABLE_SALE>
    </SALES_COMPARISON>
  </VALUATION_METHODS>
</VALUATION_RESPONSE>"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
            tmp.write(xml_content)
            tmp_path = tmp.name
        try:
            parser = XMLAppraisalParser(tmp_path)
            self.assertEqual(parser.metadata["basement_rr"], 2)
            self.assertEqual(parser.metadata["basement_br"], 1)
            self.assertEqual(parser.metadata["basement_ba"], 1.5)
            self.assertEqual(parser.metadata["basement_other"], 0)
        finally:
            os.remove(tmp_path)

    def _build_grid_pdf(self, subj_desc, subj_rooms, comp1_desc, comp1_rooms):
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        # Draw vertical grid borders matching Sales Comparison grid
        for x in (20, 105, 190, 320, 450):
            page.draw_line((x, 80), (x, 360))
        page.insert_text((25, 70), "SALES COMPARISON APPROACH", fontsize=9)
        # Header row (note COMPARABLE starts at x=210, 20pt right of x=190 border)
        page.insert_text((30, 100), "FEATURE", fontsize=8)
        page.insert_text((130, 100), "SUBJECT", fontsize=8)
        page.insert_text((210, 100), "COMPARABLE SALE NO. 1", fontsize=8)
        page.insert_text((340, 100), "COMPARABLE SALE NO. 2", fontsize=8)
        # Value Adjustments subheader
        page.insert_text((25, 160), "VALUE ADJUSTMENTS", fontsize=7)
        page.insert_text((125, 160), "DESCRIPTION", fontsize=7)
        page.insert_text((210, 160), "DESCRIPTION", fontsize=7)
        # Basement rows
        page.insert_text((25, 290), "Basement Description", fontsize=7)
        if subj_desc:
            page.insert_text((108, 290), subj_desc, fontsize=7)
        if comp1_desc:
            page.insert_text((193, 290), comp1_desc, fontsize=7)
        page.insert_text((25, 305), "Basement Finished Rooms", fontsize=7)
        if subj_rooms:
            page.insert_text((108, 305), subj_rooms, fontsize=7)
        if comp1_rooms:
            page.insert_text((193, 305), comp1_rooms, fontsize=7)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        doc.save(tmp.name)
        doc.close()
        return tmp.name

    def test_pdf_grid_ignores_comp1_when_subject_is_empty(self):
        pdf_path = self._build_grid_pdf("0sf", "", "1013sf800sfwo", "1rr0br1.0ba1o")
        try:
            m = extract_pdf_form_metrics(pdf_path)
            self.assertIsNone(m["basement_rr"])
            self.assertIsNone(m["basement_br"])
            self.assertEqual(m["basement_total_sqft"], 0)
        finally:
            os.remove(pdf_path)

    def test_pdf_grid_captures_subject_basement_counts_only(self):
        pdf_path = self._build_grid_pdf("1200sf840sfwo", "1rr0br1.0ba1o", "920sf800sfwo", "2rr3br2.0ba1o")
        try:
            m = extract_pdf_form_metrics(pdf_path)
            self.assertEqual(m["basement_total_sqft"], 1200)
            self.assertEqual(m["basement_finished_sqft"], 840)
            self.assertEqual(m["basement_rr"], 1)
            self.assertEqual(m["basement_br"], 0)
            self.assertEqual(m["basement_ba"], 1.0)
            self.assertEqual(m["basement_other"], 1)
        finally:
            os.remove(pdf_path)
