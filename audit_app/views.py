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
    total_room_photos = []

    for slot in photo_slots:
        raw_l = (slot.raw_label or '').lower()
        norm_l = (slot.normalized_label or '').lower()
        
        is_bsmt = any(w in raw_l or w in norm_l for w in basement_keywords)
        is_bed = any(b in raw_l for b in ['bedroom', 'bed', 'bdrm', 'br']) or norm_l == 'bedroom'
        is_bath = any(b in raw_l for b in ['bath', 'bathroom', 'bth', 'lavatory', 'powder']) or norm_l == 'bathroom'
        is_rec = any(w in raw_l for w in ['rec', 'recreation', 'playroom']) or (is_bsmt and any(w in raw_l for w in ['living', 'family', 'den']))
        
        groups = []
        
        if is_bsmt:
            basement_photos.append(slot)
            if is_bed:
                basement_bedroom_photos.append(slot)
                groups.append('basement_br')
            elif is_bath:
                basement_bath_photos.append(slot)
                groups.append('basement_ba')
            elif is_rec:
                basement_rec_photos.append(slot)
                groups.append('basement_rr')
            else:
                basement_other_photos.append(slot)
                groups.append('basement_other')
                
        if is_bed:
            bedroom_photos.append(slot)
            groups.append('bedrooms')
        if is_bath:
            bathroom_photos.append(slot)
            groups.append('bathrooms')
            
        # Total rooms check: "in total rroms show all photos except br, ba, basement rr, br and bth"
        # Plus subject front, rear, and street photos
        excluded_from_total_rooms = is_bed or is_bath or (is_bsmt and is_rec) or (is_bsmt and is_bed) or (is_bsmt and is_bath)
        
        is_room_keyword = any(k in raw_l or k in norm_l for k in [
            'kitchen', 'living', 'dining', 'family', 'den', 'office', 'sunroom',
            'foyer', 'hall', 'room', 'area', 'nook', 'great room', 'library', 'bonus', 'loft'
        ])
        is_subject_exterior = (
            norm_l in ['exterior front', 'exterior rear', 'street view']
            or any(k in raw_l for k in ['front view', 'rear view', 'street scene', 'subject front', 'subject rear', 'subject street'])
        ) and not any(c in raw_l or c in norm_l for c in ['comparable', 'comp ', 'rental'])
        
        if not excluded_from_total_rooms and (is_room_keyword or is_subject_exterior or norm_l in ['kitchen', 'living room', 'dining room', 'family room', 'den', 'office']):
            total_room_photos.append(slot)
            groups.append('total_rooms')
            
        slot.group_tags = " ".join(groups)

    missing_labels_list = photo_slots.filter(is_missing_label=True)
    flagged_blanks = blank_pages.filter(is_blank=True)

    context = {
        'audit': audit,
        'photo_slots': filtered_photos,
        'all_photo_slots': photo_slots,
        'missing_labels_list': missing_labels_list,
        'blank_pages': blank_pages,
        'flagged_blanks': flagged_blanks,
        'categories': categories,
        'selected_category': category_filter,
        'selected_status': status_filter,
        'bedroom_photos': bedroom_photos,
        'bathroom_photos': bathroom_photos,
        'total_room_photos': total_room_photos,
        'basement_photos': basement_photos,
        'basement_bedroom_photos': basement_bedroom_photos,
        'basement_bath_photos': basement_bath_photos,
        'basement_rec_photos': basement_rec_photos,
        'basement_other_photos': basement_other_photos,
    }
    return render(request, 'audit_app/detail.html', context)


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

