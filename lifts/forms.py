# lifts/forms.py

from django import forms
from .models import Incident

class ReportSubmissionForm(forms.ModelForm):
    class Meta:
        model = Incident
        fields = [
            'direct_cause',
            'rc_method', 'rc_man', 'rc_material', 'rc_machine', 'rc_proof',
            'corrective_action', 'corrective_action_proof',
            'permanent_action', 'permanent_action_proof',
            'contractor_acknowledgement'
        ]
        widgets = {
            'direct_cause': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'rc_method': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'rc_man': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'rc_material': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'rc_machine': forms.Textarea(attrs={'rows': 3, 'class': 'form-textarea'}),
            'corrective_action': forms.Textarea(attrs={'rows': 4, 'class': 'form-textarea'}),
            'permanent_action': forms.Textarea(attrs={'rows': 4, 'class': 'form-textarea'}),
            'rc_proof': forms.FileInput(attrs={'class': 'form-file-input'}),
            'corrective_action_proof': forms.FileInput(attrs={'class': 'form-file-input'}),
            'permanent_action_proof': forms.FileInput(attrs={'class': 'form-file-input'}),
            'contractor_acknowledgement': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

