from django import forms
import os

class ReportAuditForm(forms.Form):
    TASK_CHOICES = [
        ('all', 'Complete Audit (Photos, Labels, Bed/Bath Verification, & OpenCV Blank Pages)'),
        ('photos', 'Fast: Photo & Label Extraction Only (Tasks 1 & 2)'),
        ('blank', 'Fast: OpenCV Blank Page Detection Only (Task 3)'),
    ]

    report_file = forms.FileField(
        required=True,
        label="Upload Appraisal Report (XML / PDF)",
        help_text="Upload a MISMO 2.6 XML file (with embedded PDF) or appraisal PDF document."
    )

    tasks = forms.ChoiceField(
        choices=TASK_CHOICES,
        initial='all',
        label="Audit Scope",
        widget=forms.RadioSelect
    )

    def clean_report_file(self):
        report_file = self.cleaned_data.get('report_file')
        if not report_file:
            raise forms.ValidationError("Please select or upload an appraisal report.")
        ext = os.path.splitext(report_file.name)[1].lower()
        if ext not in ['.xml', '.pdf']:
            raise forms.ValidationError(f"Unsupported file format '{ext}'. Please upload an .xml or .pdf file.")
        return report_file
