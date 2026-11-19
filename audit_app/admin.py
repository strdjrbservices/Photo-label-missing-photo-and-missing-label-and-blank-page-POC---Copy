from django.contrib import admin
from .models import ReportAudit, AuditPhotoSlot, AuditBlankPage

class AuditPhotoSlotInline(admin.TabularInline):
    model = AuditPhotoSlot
    extra = 0
    fields = ('page_number', 'slot_name', 'raw_label', 'status', 'is_missing_label', 'blur_score', 'brightness')
    readonly_fields = fields

class AuditBlankPageInline(admin.TabularInline):
    model = AuditBlankPage
    extra = 0
    fields = ('page_number', 'classification', 'content_pixel_pct', 'edge_density_pct')
    readonly_fields = fields

@admin.register(ReportAudit)
class ReportAuditAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'property_address', 'status', 'total_bedrooms', 'bedroom_photos_identified', 'missing_label_count', 'blank_pages_count', 'created_at')
    list_filter = ('status', 'report_type', 'created_at')
    search_fields = ('file_name', 'property_address', 'appraiser_name')
    inlines = [AuditPhotoSlotInline, AuditBlankPageInline]

@admin.register(AuditPhotoSlot)
class AuditPhotoSlotAdmin(admin.ModelAdmin):
    list_display = ('report', 'page_number', 'slot_name', 'raw_label', 'status', 'is_missing_label')
    list_filter = ('status', 'is_missing_label')

@admin.register(AuditBlankPage)
class AuditBlankPageAdmin(admin.ModelAdmin):
    list_display = ('report', 'page_number', 'classification', 'is_blank', 'content_pixel_pct')
    list_filter = ('is_blank', 'classification')
