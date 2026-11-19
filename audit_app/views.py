import os
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
    }
    return render(request, 'audit_app/detail.html', context)


@require_POST
def audit_delete_view(request, audit_id):
    """Deletes an audit and redirects to the index view."""
    audit = get_object_or_404(ReportAudit, id=audit_id)
    fname = audit.file_name
    audit.delete()
    messages.info(request, f"Audit report for '{fname}' deleted.")
    return redirect('audit_index')


def quick_sample_audit_view(request, sample_name=None):
    """Fallback redirect to index."""
    return redirect('audit_index')

