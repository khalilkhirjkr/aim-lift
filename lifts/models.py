# lifts/models.py

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta

class Contractor(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='contractor',
        null=True, blank=True
    )
    name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name

class Lift(models.Model):
    premise_name = models.CharField(max_length=200)
    lift_identifier = models.CharField(max_length=100, unique=True)
    contractor_contact = models.CharField(max_length=200, blank=True)
    jkr_pic_contact = models.CharField(max_length=200, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    contractor = models.ForeignKey(
        Contractor,
        on_delete=models.SET_NULL, # Or models.PROTECT, etc.
        null=True, # Allow lifts without an assigned contractor initially
        blank=True,
        related_name='lifts' # Optional: helps query from Contractor side
    )

    def __str__(self):
        return f"{self.lift_identifier} at {self.premise_name}"

class Incident(models.Model):
    STATUS_CHOICES = [
        ('Detected', 'Detected'),
        ('Attended', 'Attended'),
        ('Pending Review', 'Pending Review'),
        ('Correction Required', 'Correction Required'),
        ('Report Submitted', 'Report Submitted'),
        ('Resolved', 'Resolved'),
    ]
    
    lift = models.ForeignKey(Lift, on_delete=models.CASCADE, related_name='incidents')
    incident_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Detected')
    timestamp = models.DateTimeField(default=timezone.now)
    is_acknowledged = models.BooleanField(default=False)
    time_attended = models.DateTimeField(null=True, blank=True)
    time_resolved = models.DateTimeField(null=True, blank=True)
    is_emergency = models.BooleanField(default=False)
    report_due_date = models.DateTimeField(null=True, blank=True)
    report_submitted_at = models.DateTimeField(null=True, blank=True)
    report_acknowledged_by_jkr = models.BooleanField(default=False)
    report_requires_correction = models.BooleanField(default=False)
    symptom = models.TextField(blank=True)
    direct_cause = models.TextField(blank=True)
    rc_method = models.TextField(blank=True, verbose_name="Root Cause: Method")
    rc_man = models.TextField(blank=True, verbose_name="Root Cause: Man")
    rc_material = models.TextField(blank=True, verbose_name="Root Cause: Material")
    rc_machine = models.TextField(blank=True, verbose_name="Root Cause: Machine")
    rc_proof = models.FileField(upload_to='proofs/', null=True, blank=True, verbose_name="Root Cause Proof")
    corrective_action = models.TextField(blank=True)
    corrective_action_proof = models.FileField(upload_to='proofs/', null=True, blank=True, verbose_name="Corrective Action Proof")
    permanent_action = models.TextField(blank=True)
    permanent_action_proof = models.FileField(upload_to='proofs/', null=True, blank=True, verbose_name="Permanent Action Proof")
    contractor_acknowledgement = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.incident_type} ({self.status}) at {self.lift.lift_identifier}"

    def met_sla(self):
        if not self.time_attended:
            return False
        sla_duration = timedelta(minutes=30) if self.is_emergency else timedelta(hours=24)
        return (self.time_attended - self.timestamp) <= sla_duration

