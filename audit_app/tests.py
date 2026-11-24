from django.test import TestCase, Client
from django.urls import reverse
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
