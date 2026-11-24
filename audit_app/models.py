from django.db import models
import os

class ReportAudit(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    file_name = models.CharField(max_length=255)
    original_file = models.FileField(upload_to='uploads/%Y/%m/%d/', blank=True, null=True)
    report_type = models.CharField(max_length=10, default='XML')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    execution_time_seconds = models.FloatField(default=0.0)

    # XML Property metadata
    property_address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    appraiser_name = models.CharField(max_length=150, blank=True, null=True)
    lender_name = models.CharField(max_length=150, blank=True, null=True)
    total_rooms = models.IntegerField(blank=True, null=True)
    total_bedrooms = models.IntegerField(blank=True, null=True)
    total_bathrooms = models.FloatField(blank=True, null=True)
    gross_living_area = models.FloatField(blank=True, null=True)
    appraised_value = models.CharField(max_length=50, blank=True, null=True)
    mismo_version = models.CharField(max_length=20, blank=True, null=True)

    # Basement Grid Analysis (Rooms Below Grade from Sales Grid)
    basement_rr = models.IntegerField(blank=True, null=True, verbose_name="Basement Rec Rooms")
    basement_br = models.IntegerField(blank=True, null=True, verbose_name="Basement Bedrooms")
    basement_ba = models.FloatField(blank=True, null=True, verbose_name="Basement Bathrooms")
    basement_other = models.IntegerField(blank=True, null=True, verbose_name="Basement Other Rooms")
    basement_total_sqft = models.IntegerField(blank=True, null=True, verbose_name="Basement Total Sqft")
    basement_finished_sqft = models.IntegerField(blank=True, null=True, verbose_name="Basement Finished Sqft")
    basement_rooms_summary = models.CharField(max_length=100, blank=True, null=True, verbose_name="Basement UAD Summary")

    # Audit statistics
    total_slots_scanned = models.IntegerField(default=0)
    labeled_photos_count = models.IntegerField(default=0)
    missing_label_count = models.IntegerField(default=0)
    bedroom_photos_identified = models.IntegerField(default=0)
    bathroom_photos_identified = models.IntegerField(default=0)
    total_pages_scanned = models.IntegerField(default=0)
    blank_pages_count = models.IntegerField(default=0)

    # Artifact paths (relative to MEDIA_ROOT)
    excel_report = models.FileField(upload_to='audit_reports/', blank=True, null=True)
    json_report = models.FileField(upload_to='audit_reports/', blank=True, null=True)
    extracted_pdf_path = models.CharField(max_length=500, blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.file_name} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

    @property
    def room_photos_identified(self):
        """Count of photos labeled as major living rooms (bedrooms, kitchen, living, dining, family/den, solarium, mudroom)."""
        count = 0
        for slot in self.photo_slots.all():
            if slot.has_image:
                lbl = f"{slot.normalized_label or ''} {slot.raw_label or ''}".lower()
                if any(k in lbl for k in ['bedroom', 'bed', 'kitchen', 'living', 'dining', 'family', 'den', 'office', 'sunroom', 'solarium', 'mudroom', 'mud room']):
                    count += 1
        return count

    @property
    def total_rooms_discrepancy(self):
        """Returns True if declared total rooms differs from photo evidence."""
        if self.total_rooms is not None:
            return self.room_photos_identified != self.total_rooms
        return False

    @property
    def bedroom_discrepancy(self):
        """Returns True if declared bedrooms differs from photo evidence."""
        if self.total_bedrooms is not None:
            return self.bedroom_photos_identified != self.total_bedrooms
        return False

    @property
    def bathroom_discrepancy(self):
        """Returns True if declared bathrooms differs from photo evidence."""
        if self.total_bathrooms is not None:
            return int(self.bathroom_photos_identified) < int(self.total_bathrooms)
        return False

    @property
    def basement_rec_discrepancy(self):
        """Returns True if declared basement rec rooms differs from photo evidence."""
        if self.basement_rr is not None:
            count = 0
            for slot in self.photo_slots.all():
                if slot.has_image:
                    raw_l = (slot.raw_label or '').lower()
                    norm_l = (slot.normalized_label or '').lower()
                    if any(w in raw_l or w in norm_l for w in ['basement', 'bsmt', 'cellar', 'lower level', 'below grade', 'rec room', 'recreation room']):
                        if any(w in raw_l for w in ['rec', 'recreation', 'living', 'family', 'den', 'playroom']) or norm_l == 'living room':
                            count += 1
            return count != self.basement_rr
        return False

    @property
    def basement_bedroom_discrepancy(self):
        """Returns True if declared basement bedrooms differs from photo evidence."""
        if self.basement_br is not None:
            count = 0
            for slot in self.photo_slots.all():
                if slot.has_image:
                    raw_l = (slot.raw_label or '').lower()
                    norm_l = (slot.normalized_label or '').lower()
                    if any(w in raw_l or w in norm_l for w in ['basement', 'bsmt', 'cellar', 'lower level', 'below grade']):
                        if any(b in raw_l for b in ['bedroom', 'bed', 'bdrm', 'br']) or norm_l == 'bedroom':
                            count += 1
            return count != self.basement_br
        return False

    @property
    def basement_bathroom_discrepancy(self):
        """Returns True if declared basement bathrooms differs from photo evidence."""
        if self.basement_ba is not None:
            count = 0
            for slot in self.photo_slots.all():
                if slot.has_image:
                    raw_l = (slot.raw_label or '').lower()
                    norm_l = (slot.normalized_label or '').lower()
                    if any(w in raw_l or w in norm_l for w in ['basement', 'bsmt', 'cellar', 'lower level', 'below grade']):
                        if any(b in raw_l for b in ['bath', 'bathroom', 'bth', 'lavatory', 'powder']) or norm_l == 'bathroom':
                            count += 1
            return int(count) < int(self.basement_ba)
        return False

    @property
    def basement_other_discrepancy(self):
        """Returns True if declared basement other rooms differs from photo evidence."""
        if self.basement_other is not None:
            count = 0
            for slot in self.photo_slots.all():
                if slot.has_image:
                    raw_l = (slot.raw_label or '').lower()
                    norm_l = (slot.normalized_label or '').lower()
                    if any(w in raw_l or w in norm_l for w in ['basement', 'bsmt', 'cellar', 'lower level', 'below grade']):
                        is_br = any(b in raw_l for b in ['bedroom', 'bed', 'bdrm', 'br']) or norm_l == 'bedroom'
                        is_ba = any(b in raw_l for b in ['bath', 'bathroom', 'bth', 'lavatory', 'powder']) or norm_l == 'bathroom'
                        is_rec = any(w in raw_l for w in ['rec', 'recreation', 'living', 'family', 'den', 'playroom']) or norm_l == 'living room'
                        if not is_br and not is_ba and not is_rec:
                            count += 1
            return count != self.basement_other
        return False


class AuditPhotoSlot(models.Model):
    STATUS_CHOICES = [
        ('LABELED', 'Labeled'),
        ('MISSING_LABEL', 'Missing Label'),
        ('MISSING_PHOTO', 'Missing Photo'),
        ('EMPTY_SLOT', 'Empty Slot'),
    ]

    report = models.ForeignKey(ReportAudit, on_delete=models.CASCADE, related_name='photo_slots')
    page_number = models.IntegerField()
    slot_name = models.CharField(max_length=100)
    raw_label = models.CharField(max_length=255, blank=True, default='')
    normalized_label = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EMPTY_SLOT')
    has_image = models.BooleanField(default=False)
    is_missing_label = models.BooleanField(default=False)
    
    # Stored image file path relative to MEDIA_URL
    image_relative_path = models.CharField(max_length=500, blank=True, null=True)
    
    # Image metrics
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    aspect_ratio = models.FloatField(null=True, blank=True)
    blur_score = models.FloatField(null=True, blank=True)
    brightness = models.FloatField(null=True, blank=True)
    is_blurry = models.BooleanField(default=False)
    verification_note = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['page_number', 'slot_name']

    def __str__(self):
        return f"Page {self.page_number} - {self.slot_name} ({self.status})"


class AuditBlankPage(models.Model):
    report = models.ForeignKey(ReportAudit, on_delete=models.CASCADE, related_name='blank_pages')
    page_number = models.IntegerField()
    is_blank = models.BooleanField(default=False)
    classification = models.CharField(max_length=50, default='NON_BLANK')
    content_pixel_pct = models.FloatField(default=0.0)
    laplacian_var = models.FloatField(default=0.0)
    edge_density_pct = models.FloatField(default=0.0)
    total_text_lines = models.IntegerField(default=0)
    sample_header = models.TextField(blank=True, default='')
    preview_relative_path = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        ordering = ['page_number']

    def __str__(self):
        return f"Page {self.page_number} - {self.classification}"
