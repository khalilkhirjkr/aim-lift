# lifts/admin.py

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from datetime import timedelta
from .models import Lift, Incident, Contractor

@admin.register(Lift)
class LiftAdmin(admin.ModelAdmin):
    list_display = ('lift_identifier', 'premise_name', 'contractor_contact', 'jkr_pic_contact')
    search_fields = ('lift_identifier', 'premise_name')

@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        'lift', 
        'incident_type', 
        'status', 
        'timestamp', 
        'time_attended',
        'report_submitted_at',
        'report_acknowledged_by_jkr',
        'review_report_button'
    )
    list_filter = ('status', 'report_acknowledged_by_jkr', 'lift__premise_name')
    search_fields = ('lift__lift_identifier', 'incident_type', 'lift__premise_name')
    actions = ['acknowledge_incident', 'approve_report_action', 'request_correction_action']

    def acknowledge_incident(self, request, queryset):
        for incident in queryset:
            if not incident.time_attended:
                incident.time_attended = timezone.now()
            
            # Set the report due date if it hasn't been set
            if not incident.report_due_date:
                if incident.is_emergency:
                    incident.report_due_date = incident.time_attended + timedelta(weeks=2)
                else:
                    incident.report_due_date = incident.time_attended + timedelta(weeks=3)

            incident.is_acknowledged = True
            incident.status = 'Attended'
            incident.save()
    acknowledge_incident.short_description = "Acknowledge/Silence selected incidents"

    def approve_report_action(self, request, queryset):
        queryset.update(
            report_acknowledged_by_jkr=True,
            status='Resolved',
            report_requires_correction=False
        )
    approve_report_action.short_description = "Approve selected reports"

    def request_correction_action(self, request, queryset):
        queryset.update(
            report_requires_correction=True,
            status='Correction Required'
        )
    request_correction_action.short_description = "Request correction for selected reports"

    def review_report_button(self, obj):
        if obj.status in ['Pending Review', 'Correction Required', 'Resolved']:
            url = reverse('review_report', args=[obj.id])
            return format_html('<a class="button" href="{}">Review Report</a>', url)
        return "N/A"
    review_report_button.short_description = 'Review'

admin.site.register(Contractor)