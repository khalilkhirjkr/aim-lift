# lifts/serializers.py
from rest_framework import serializers
from .models import Lift, Incident

class LiftSerializer(serializers.ModelSerializer):
    """
    Serializer for the Lift model, including location.
    """
    class Meta:
        model = Lift
        fields = ['id', 'lift_identifier', 'premise_name', 'latitude', 'longitude', 'contractor']


class IncidentSerializer(serializers.ModelSerializer):
    """
    Serializer for the Incident model (flattened for Flutter).
    Includes lift-related fields like latitude and longitude directly.
    """
    lift_identifier = serializers.CharField(source='lift.lift_identifier', read_only=True)
    premise_name = serializers.CharField(source='lift.premise_name', read_only=True)
    latitude = serializers.FloatField(source='lift.latitude', read_only=True)
    longitude = serializers.FloatField(source='lift.longitude', read_only=True)
    met_sla = serializers.BooleanField(read_only=True)

    class Meta:
        model = Incident
        fields = [
            'id',
            'incident_type',
            'timestamp',
            'status',
            'is_emergency',
            'time_attended',
            'time_resolved',
            'met_sla',
            'lift_identifier',
            'premise_name',
            'latitude',
            'longitude',
        ]

class IncidentReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = [
            'direct_cause',
            'rc_machine',
            'rc_method',
            'rc_man',
            'rc_material',
            'corrective_action',
            'permanent_action',
            'contractor_acknowledgement',
        ]

