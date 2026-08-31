# lifts/views.py

import os
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, F, Subquery, OuterRef
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import joblib
import json
import numpy as np
import pandas as pd
import random

from rest_framework.decorators import api_view, permission_classes
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status

from django.db import connection

from .forms import ReportSubmissionForm
from .models import Lift, Incident, Contractor, SensorReading
from .predictor import predict_lift_health, EXPECTED_FEATURES, model as PREDICTIVE_MODEL
from .serializers import LiftSerializer, IncidentSerializer, IncidentReportSerializer
from .telegram_bot import send_telegram_message


# ==================================
# ===== SENSOR READING PIPELINE ====
# ==================================

# How many recent readings to keep per lift (oldest are auto-deleted on ingest).
READINGS_KEEP_PER_LIFT = int(os.environ.get('SENSOR_READINGS_KEEP', '200'))
# Minimum model confidence (%) before a predicted-failure incident is opened.
PREDICT_ALERT_CONFIDENCE = float(os.environ.get('PREDICT_ALERT_CONFIDENCE', '80'))

# Named reading profiles for the test/inject tools. Values are (low, high) ranges.
READING_PROFILES = {
    'normal': {
        'feature_p1': (297, 301), 'feature_p2': (308, 309.5), 'feature_p3': (1450, 1550),
        'feature_s1': (35, 45), 'feature_s2': (10, 150), 'feature_s3': (10, 80),
        'vibration': (0.1, 3.0), 'vertical_acceleration_mps2': (0.01, 0.15), 'acoustic_db': (55, 63),
    },
    'high_vibration': {'vibration': (20, 50)},
    'high_acoustic': {'acoustic_db': (80, 100)},
    'fault': {'vibration': (20, 50), 'acoustic_db': (80, 100)},
}
_NOT_A_FAILURE = {'No failure', 'Prediction Error', 'Model Not Loaded', 'Encoder Not Loaded'}


def build_reading_values(profile='normal'):
    """Return a dict of the 9 feature values for a named profile. Starts from
    'normal' and overlays the chosen profile's ranges."""
    ranges = dict(READING_PROFILES['normal'])
    ranges.update(READING_PROFILES.get(profile, {}))
    return {f: round(random.uniform(*ranges[f]), 4) for f in EXPECTED_FEATURES if f in ranges}


def process_reading(lift, values, *, device_id='', source='device'):
    """Core ingest: store the reading, run the model, open a predicted-failure
    incident if warranted, then trim the per-lift rolling window.
    Returns the saved SensorReading."""
    reading = SensorReading(lift=lift, device_id=device_id or '', source=source)
    for f in EXPECTED_FEATURES:
        try:
            setattr(reading, f, float(values.get(f, 0) or 0))
        except (TypeError, ValueError):
            setattr(reading, f, 0.0)

    pred, conf = predict_lift_health(reading.feature_dict())
    reading.prediction = pred or ''
    try:
        reading.confidence = round(float(conf) * 100, 2)
    except (TypeError, ValueError):
        reading.confidence = 0.0

    if pred not in _NOT_A_FAILURE and reading.confidence >= PREDICT_ALERT_CONFIDENCE:
        already_open = Incident.objects.filter(
            lift=lift, status='Detected', incident_type__startswith='Predicted:'
        ).exists()
        if not already_open:
            incident = Incident.objects.create(
                lift=lift,
                incident_type=f'Predicted: {pred}',
                status='Detected',
                is_emergency=True,
            )
            reading.incident = incident
            send_telegram_message(
                f"\U0001F52E *Predicted Lift Failure* \U0001F52E\n\n"
                f"*Premise:* {lift.premise_name}\n"
                f"*Lift ID:* {lift.lift_identifier}\n"
                f"*Prediction:* {pred} ({reading.confidence:.1f}% confidence)\n"
                f"*Vibration:* {reading.vibration:.2f} | *Acoustic:* {reading.acoustic_db:.2f} dB"
            )

    reading.save()

    stale_ids = list(
        SensorReading.objects.filter(lift=lift)
        .order_by('-created_at')
        .values_list('id', flat=True)[READINGS_KEEP_PER_LIFT:]
    )
    if stale_ids:
        SensorReading.objects.filter(id__in=stale_ids).delete()

    return reading


@csrf_exempt
def ingest_reading(request):
    """POST /api/iot/reading/ — a lift's IoT unit submits a sensor reading.
    Requires header  X-Device-Key: <IOT_DEVICE_KEY>."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    expected_key = os.environ.get('IOT_DEVICE_KEY', '')
    if not expected_key or request.headers.get('X-Device-Key', '') != expected_key:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    lift_id = data.get('lift_id')
    try:
        lift = Lift.objects.get(lift_identifier=lift_id)
    except Lift.DoesNotExist:
        return JsonResponse({'error': f'unknown lift_id {lift_id!r}'}, status=404)

    reading = process_reading(lift, data, device_id=data.get('device_id', ''), source='device')
    return JsonResponse({
        'status': 'ok',
        'prediction': reading.prediction,
        'confidence': reading.confidence,
        'incident_opened': reading.incident_id is not None,
    }, status=201)


@staff_member_required
def inject_test_reading(request):
    """Staff-only QA tool: submit a reading through the real pipeline using a
    named profile. POST { lift_id, profile }."""
    if request.method != 'POST':
        return redirect('lift_health')
    lift = get_object_or_404(Lift, id=request.POST.get('lift_id'))
    profile = request.POST.get('profile', 'normal')
    if profile not in READING_PROFILES:
        profile = 'normal'
    process_reading(lift, build_reading_values(profile), device_id='TEST-INJECT', source='test')
    return redirect(f"{reverse('lift_health')}?lift_id={lift.id}")


def landing(request):
    """Public marketing / entry page. No auth. Logged-in users go straight to
    the dashboard."""
    if request.user.is_authenticated:
        return redirect('incident_list')
    return render(request, 'landing.html')


@csrf_exempt
def healthz(request):
    """Lightweight health check. Touches the DB so an external pinger keeps both
    the web dyno and the Supabase compute warm. No auth, no side effects."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return JsonResponse({"status": "ok"})
    except Exception as exc:  # pragma: no cover - diagnostics only
        return JsonResponse({"status": "error", "detail": str(exc)}, status=503)

# ==================================
# ========== CONSTANTS =============
# ==================================

# --- Sensor Thresholds ---
# *** REVIEW AND ADJUST THESE RANGES BASED ON YOUR SENSORS / DATA ***
SENSOR_THRESHOLDS = {
    # What do p1-p3 and s1-s3 measure? Set realistic min/max.
    'feature p1': {'min': 296, 'max': 303},  # Air Temp K (e.g., based on 25%-75% +/- buffer)
    'feature p2': {'min': 307, 'max': 311},  # Process Temp K (e.g., based on 25%-75% +/- buffer)
    'feature p3': {'min': 1400, 'max': 1600}, # Rotational Speed rpm (e.g., based on 25%-75% +/- buffer)
    'feature s1': {'min': 30, 'max': 50},    # Torque Nm (e.g., based on 25%-75% +/- buffer)
    'feature s2': {'min': 0, 'max': 200},   # Tool Wear min (e.g., 0 to a reasonable max wear)
    'feature s3': {'min': 0, 'max': 100},   # Example - ADJUST (Needs real range)
    # These were simulated, ranges might be okay but review based on expected real sensors
    'vibration': {'min': 0, 'max': 15},
    'vertical acceleration mps2': {'min': 0, 'max': 0.5}, # Example - ADJUST
    'acoustic db': {'min': 50, 'max': 70}, # Example - ADJUST
}

# ==================================
# ========== DASHBOARDS ============
# ==================================

# lifts/views.py

# ... (keep all your imports at the top of the file) ...

@login_required
def lift_search(request):
    """Global top-bar search. Matches a lift by identifier or premise name.
    One hit -> jump straight to its health page; otherwise show a result list."""
    q = (request.GET.get('q') or '').strip()
    lifts = []
    if q:
        lifts = list(
            Lift.objects.filter(
                Q(lift_identifier__icontains=q) | Q(premise_name__icontains=q)
            ).order_by('lift_identifier')[:50]
        )
        if len(lifts) == 1:
            return redirect(f"{reverse('lift_health')}?lift_id={lifts[0].id}")
    return render(request, 'lifts/lift_search.html', {'q': q, 'lifts': lifts})


@login_required
def incident_list(request):
    incidents = Incident.objects.all().order_by('-timestamp')

    # --- FIX 1: Define the active_incidents queryset ---
    active_incidents = incidents.filter(status='Detected') # Store the queryset
    active_incidents_count = active_incidents.count()    # Count from the queryset
    # --- End Fix ---

    attended_incidents = incidents.filter(time_attended__isnull=False)
    met_sla_count = sum(1 for incident in attended_incidents if incident.met_sla())

    if attended_incidents.count() > 0:
        sla_percentage = round((met_sla_count / attended_incidents.count()) * 100)
    else:
        sla_percentage = 100

    # --- FIX 2: Send ONLY active incidents to the map ---
    active_incidents_locations = []
    # Iterate through the active incidents and get their lift coordinates
    # .select_related('lift') makes this efficient (one query)
    for incident in active_incidents.select_related('lift'):
        if incident.lift.latitude and incident.lift.longitude:
            active_incidents_locations.append({
                'lat': incident.lift.latitude,
                'lng': incident.lift.longitude,
                'popup': f"<b>{incident.incident_type}</b><br>{incident.lift.lift_identifier}" # Popup text
            })
    
    # This JSON list now only contains active incidents
    active_incidents_json = json.dumps(active_incidents_locations, cls=DjangoJSONEncoder)
    # --- END FIX 2 ---


    # --- FIND LATEST ACTIVE INCIDENT LOCATION (for focusing) ---
    latest_active_incident_location = None
    latest_active_incident = active_incidents.first() # This line will now work
    if latest_active_incident and latest_active_incident.lift.latitude and latest_active_incident.lift.longitude:
        latest_active_incident_location = {
            'lat': latest_active_incident.lift.latitude,
            'lng': latest_active_incident.lift.longitude,
            'popup': f"<b>Latest Active Incident:</b><br>{latest_active_incident.lift.lift_identifier}<br>{latest_active_incident.incident_type}"
        }
    latest_active_incident_json = json.dumps(latest_active_incident_location) # Convert dict to JSON
    # --- END FIND LOCATION ---

    context = {
        'incidents': incidents,
        'active_incidents_count': active_incidents_count,
        'sla_percentage': sla_percentage,
        # 'lifts_json': lifts_json, # <-- REMOVED (No longer sending all lifts)
        'active_incidents_json': active_incidents_json, # <-- ADDED
        'latest_active_incident_json': latest_active_incident_json, 
    }
    return render(request, 'lifts/incident_list.html', context)


@login_required
def contractor_dashboard(request):
     # (Existing contractor_dashboard logic)
    incidents = Incident.objects.all().order_by('-timestamp')
    now = timezone.now()

    # Calculate Report Submission KPI
    incidents_requiring_report = incidents.filter(
        time_attended__isnull=False,
        report_due_date__isnull=False
    )
    due_incidents = incidents_requiring_report.filter(report_due_date__lt=now)
    total_due = due_incidents.count()
    if total_due > 0:
        on_time_submissions = due_incidents.filter(
            report_submitted_at__isnull=False,
            report_submitted_at__lte=F('report_due_date') # Submitted date <= Due date
        ).count()
        report_submission_kpi = round((on_time_submissions / total_due) * 100)
    else:
        report_submission_kpi = 100 # No reports past due yet, so 100% on time

    # Calculate Contractor Reliability KPI
    submitted_reports = incidents.filter(report_submitted_at__isnull=False)
    total_submitted = submitted_reports.count()
    if total_submitted > 0:
        acknowledged_final = submitted_reports.filter(report_acknowledged_by_jkr=True).count()
        contractor_reliability_kpi = round((acknowledged_final / total_submitted) * 100)
    else:
        contractor_reliability_kpi = 0

    context = {
        'incidents': incidents,
        'report_submission_kpi': report_submission_kpi,
        'contractor_reliability_kpi': contractor_reliability_kpi,
    }
    return render(request, 'lifts/contractor_dashboard.html', context)


# --- Lift Health View (Alert check removed) ---
@login_required
def lift_health_dashboard(request):
    all_lifts = Lift.objects.all().order_by('lift_identifier')
    selected_lift_id = request.GET.get('lift_id')
    selected_lift = None
    if selected_lift_id:
        selected_lift = get_object_or_404(Lift, id=selected_lift_id)
    elif all_lifts:
        selected_lift = all_lifts.first()

    prediction = None
    confidence = 0
    prediction_error = None
    sensor_data_with_thresholds = []
    latest_reading = None
    recent_readings = []

    if selected_lift:
        latest_reading = SensorReading.objects.filter(lift=selected_lift).order_by('-created_at').first()
        recent_readings = list(SensorReading.objects.filter(lift=selected_lift).order_by('-created_at')[:20])

        if latest_reading:
            prediction = latest_reading.prediction or None
            confidence = latest_reading.confidence
            for feature in EXPECTED_FEATURES:
                threshold = SENSOR_THRESHOLDS.get(feature.replace('_', ' '))
                if threshold:
                    sensor_data_with_thresholds.append({
                        'name': feature.replace('_', ' '),
                        'value': getattr(latest_reading, feature),
                        'min': threshold['min'],
                        'max': threshold['max'],
                    })
            if prediction in ('Model Not Loaded', 'Encoder Not Loaded'):
                prediction_error = "Predictive model could not be loaded on the server."

    context = {
        'all_lifts': all_lifts,
        'selected_lift': selected_lift,
        'latest_reading': latest_reading,
        'recent_readings': recent_readings,
        'prediction': prediction,
        'confidence': confidence,
        'sensor_data': sensor_data_with_thresholds,
        'prediction_error': prediction_error,
        'reading_profiles': list(READING_PROFILES.keys()),
    }
    return render(request, 'lifts/lift_health.html', context)


# ==================================
# ==== PRESENTATION SIMULATION =====
# ==================================
# (UPDATED load_future_data function)
def load_future_data(request):
    """
    Loads the last failure entry from 'future_log_data.csv',
    creates a corresponding 'Predicted:' incident, simulates CLEAR failure data,
    and sends a detailed Telegram alert using the simulated data.
    This is for DEMONSTRATION PURPOSES ONLY.
    """
    try:
        df = pd.read_csv('future_log_data.csv') # Assumes file is in project root
        failure_rows = df[df['failure_type'] != 'No failure'] # Find rows indicating failure

        if failure_rows.empty:
             print("[INFO] No failure rows found in future_log_data.csv to load.")
             return redirect('lift_health')

        # Get the data from the last failure entry in the CSV (just for lift ID and failure type)
        failure_row = failure_rows.iloc[-1]

        lift_identifier = failure_row['lift_identifier']
        # Find the corresponding Lift object in the database
        lift_instance = Lift.objects.get(lift_identifier=lift_identifier)

        # Use the actual failure type from the CSV for the incident
        incident_type_from_csv = failure_row['failure_type']

        # Create the incident type string
        incident_type_str = f"Predicted: {incident_type_from_csv}"

        # Create the new incident record and assign it
        new_incident = Incident.objects.create(
            lift=lift_instance,
            incident_type=incident_type_str,
            timestamp=timezone.now(), # Use current time
            status='Detected',
            is_emergency=True # Assume predicted failures from file are emergencies
        )
        print(f"[INFO] Created simulated incident '{incident_type_str}' for lift {lift_identifier} from future data.")

        # --- GENERATE SIMULATED DATA (like dashboard) ---
        print("--- Generating simulated data for Telegram alert ---")
        # Start with base normal readings
        latest_readings_raw = {
            'feature_p1': np.random.uniform(297, 301),
            'feature_p2': np.random.uniform(308, 309.5),
            'feature_p3': np.random.uniform(1450, 1550),
            'feature_s1': np.random.uniform(35, 45),
            'feature_s2': np.random.uniform(10, 150),
            'feature_s3': np.random.uniform(10, 80),
            'vibration': np.random.uniform(0.1, 3.0),
            'vertical_acceleration_mps2': np.random.uniform(0.01, 0.15),
            'acoustic_db': np.random.uniform(55, 63),
        }
        # Ensure all features expected by the model are present
        for feature in EXPECTED_FEATURES:
            if feature not in latest_readings_raw:
                latest_readings_raw[feature] = 0.0

        # Apply the CLEAR failure simulation (matching dashboard)
        latest_readings_raw['vibration'] = np.random.uniform(20, 50)   # Matches generator
        latest_readings_raw['acoustic_db'] = np.random.uniform(80, 100) # Matches generator
        # Note: feature_p2 and feature_s1 remain normal here, matching dashboard sim logic
        print(f"--- Simulated values for alert: {latest_readings_raw} ---")
        # --- END OF SIMULATED DATA GENERATION ---


        # --- SEND DETAILED TELEGRAM ALERT (Using Simulated Data) ---
        try:
            # --- Build Abnormal Readings String (from simulated data) ---
            abnormal_readings_details = ""
            # Prepare sensor_data_with_thresholds like in the dashboard view
            sensor_data_for_alert = []
            for key, value in latest_readings_raw.items():
                 if key in EXPECTED_FEATURES:
                     threshold_key = key.replace('_', ' ')
                     threshold = SENSOR_THRESHOLDS.get(threshold_key)
                     if threshold:
                          sensor_data_for_alert.append({
                              'name': threshold_key,
                              'value': value,
                              'min': threshold['min'],
                              'max': threshold['max']
                          })

            # Now build the string using this list
            for sensor_info in sensor_data_for_alert:
                s_name = sensor_info['name']
                s_value = float(sensor_info['value']) # Ensure float
                s_min = sensor_info['min']
                s_max = sensor_info['max']
                is_abnormal = False
                try:
                    if (isinstance(s_min, (int, float)) and s_value < s_min): is_abnormal = True
                    if (isinstance(s_max, (int, float)) and s_value > s_max): is_abnormal = True
                except (ValueError, TypeError): is_abnormal = False

                if is_abnormal:
                    abnormal_readings_details += (
                        f"- {s_name.title()}: {s_value:.2f} *(Abnormal)*\n"
                        f"  (Normal: {s_min} - {s_max})\n"
                    )

            # --- Define Recommendations ---
            recommendations = "Recommendations:\n"
            if incident_type_from_csv == 'Random failure':
                 recommendations += "- Perform general inspection of lift components.\n- Check for intermittent electrical issues.\n- Review recent maintenance logs."
            elif incident_type_from_csv in ['door close delay', 'door open delay']:
                 recommendations += "- Inspect door tracks for obstructions.\n- Check door sensors and safety edges.\n- Verify door motor operation and controller settings."
            elif incident_type_from_csv == 'drive delay':
                 recommendations += "- Inspect motor drive unit and connections.\n- Check power supply to the drive.\n- Verify controller parameters related to drive operation."
            elif incident_type_from_csv == 'signal delay':
                 recommendations += "- Inspect call buttons and wiring.\n- Check controller communication network.\n- Verify controller logic for signal processing."
            else:
                 recommendations += "- Conduct a thorough inspection based on the predicted failure type.\n- Consult lift maintenance manual for specific troubleshooting steps."


            # --- Construct the final Telegram message ---
            message = (
                f"🚨 *Incident Prediction Alert* 🚨\n\n" # Updated Title
                f"*Premise:* {lift_instance.premise_name}\n"
                f"*Lift ID:* {lift_instance.lift_identifier}\n"
                f"*Predicted Failure:* {incident_type_from_csv}\n"
                f"*Time:* {timezone.localtime(new_incident.timestamp).strftime('%d-%b-%Y %I:%M %p')}\n\n" # Use new_incident
            )
            if abnormal_readings_details:
                # Updated title for clarity
                message += f"*Detail of Simulated Abnormal Readings:*\n{abnormal_readings_details}\n"
            message += f"{recommendations}" # Add recommendations

            send_telegram_message(message)
            print("[INFO] Detailed Telegram alert sent for simulated incident (using simulated data).")

        except Exception as telegram_error:
            print(f"[ERROR] Failed to send detailed Telegram alert for simulated incident: {telegram_error}")
        # --- END OF TELEGRAM ALERT CODE ---

        lift_id_for_redirect = lift_instance.id

    except FileNotFoundError:
        print("[ERROR] future_log_data.csv not found.")
        return redirect('lift_health')
    except Lift.DoesNotExist:
        print(f"[ERROR] Lift with identifier '{lift_identifier}' not found in database.")
        return redirect('lift_health')
    except (IndexError, KeyError, ValueError) as e:
         print(f"[ERROR] Error reading future_log_data.csv: {e}. Check file format/content.")
         return redirect('lift_health')
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred in load_future_data: {e}")
        return redirect('lift_health')

    # Redirect to the health page for the specific lift that was updated
    return redirect(f'/health/?lift_id={lift_id_for_redirect}')


# ==================================
# ======== API FOR ESP32 ===========
# ==================================
# (Keep existing handle_alert function)
@csrf_exempt
def handle_alert(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lift_id = data.get('lift_id')
            incident_type = data.get('incident_type')
            status = data.get('status')
            device_id = data.get('device_id') # Optional
            premise_name = data.get('premise') # Optional

            lift_instance = get_object_or_404(Lift, lift_identifier=lift_id)
            print(f"Received alert: lift_id={lift_id}, type={incident_type}, status={status}")

            if status == 'Detected':
                is_emergency = (incident_type == "Mantrap" or "Predicted:" in incident_type)
                incident = Incident.objects.create(
                    lift=lift_instance,
                    incident_type=incident_type,
                    status='Detected',
                    is_emergency=is_emergency
                )
                print(f"Created Incident ID: {incident.id}")

                message = (
                    f"🚨 *New Lift Incident Alert* 🚨\n\n"
                    f"*Premise:* {lift_instance.premise_name}\n"
                    f"*Lift ID:* {lift_instance.lift_identifier}\n"
                    f"*Incident:* {incident_type}\n"
                    f"*Time:* {incident.timestamp.strftime('%d-%b-%Y %I:%M %p')}"
                )
                send_telegram_message(message)
                return JsonResponse({'status': 'success', 'message': 'Incident reported'}, status=201)

            elif status == 'Attended':
                incident = Incident.objects.filter(lift=lift_instance, status='Detected').order_by('-timestamp').first()
                if incident:
                    incident.status = 'Attended'
                    incident.time_attended = timezone.now()
                    if not incident.report_due_date:
                         incident.report_due_date = incident.time_attended + (timedelta(weeks=2) if incident.is_emergency else timedelta(weeks=3))
                    incident.save()
                    print(f"Updated Incident ID: {incident.id} to Attended")

                    message = (
                        f"✅ *Incident Attended On-Site* ✅\n\n"
                        f"*Premise:* {lift_instance.premise_name}\n"
                        f"*Lift ID:* {lift_instance.lift_identifier}\n"
                        f"*Incident:* {incident.incident_type}\n"
                        f"*Time Attended:* {incident.time_attended.strftime('%d-%b-%Y %I:%M %p')}"
                    )
                    send_telegram_message(message)
                    return JsonResponse({'status': 'success', 'message': 'Incident status updated to Attended'}, status=200)
                else:
                    print(f"No 'Detected' incident found for lift {lift_id} to mark as Attended.")
                    return JsonResponse({'status': 'error', 'message': 'No active incident found to mark as attended'}, status=404)

            else:
                 print(f"Invalid status received: {status}")
                 return JsonResponse({'status': 'error', 'message': 'Invalid status value'}, status=400)

        except json.JSONDecodeError:
            print("[ERROR] Invalid JSON received in handle_alert")
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)
        except Lift.DoesNotExist:
            print(f"[ERROR] Lift with identifier '{lift_id}' not found in handle_alert")
            return JsonResponse({'status': 'error', 'message': 'Lift identifier not found'}, status=404)
        except KeyError as e:
            print(f"[ERROR] Missing key in JSON data in handle_alert: {e}")
            return JsonResponse({'status': 'error', 'message': f'Missing data: {e}'}, status=400)
        except Exception as e:
             print(f"[ERROR] Unexpected error in handle_alert: {e}")
             return JsonResponse({'status': 'error', 'message': 'An internal server error occurred'}, status=500)

    else: # Only POST is allowed
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

# (Keep existing check_status function)
@csrf_exempt
def check_status(request):
    if request.method == 'GET':
        device_id = request.GET.get('device_id')
        incident_to_silence = Incident.objects.filter(
            is_acknowledged=True, status='Attended'
        ).order_by('-timestamp').first()

        if incident_to_silence:
            incident_to_silence.is_acknowledged = False
            incident_to_silence.save()
            print(f"Sending SILENCE command for Incident ID {incident_to_silence.id} (Device: {device_id})")
            return JsonResponse({'command': 'silence'})
        else:
            return JsonResponse({})
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


# ==================================
# ====== REPORT WORKFLOW ===========
# ==================================
# (Keep existing submit_report_form function)
@login_required
def submit_report_form(request, incident_id):
    incident = get_object_or_404(Incident, id=incident_id)
    if incident.status not in ['Attended', 'Correction Required']:
        return redirect('contractor_dashboard')

    if request.method == 'POST':
        form = ReportSubmissionForm(request.POST, request.FILES, instance=incident)
        if form.is_valid():
            if not incident.symptom:
                 incident.symptom = incident.incident_type
            incident.status = 'Pending Review'
            incident.report_submitted_at = timezone.now()
            incident.report_requires_correction = False
            form.save()
            print(f"Report submitted for Incident ID: {incident.id}")

            message = (
                f"📝 *Incident Report Submitted* 📝\n\n"
                f"*Premise:* {incident.lift.premise_name}\n"
                f"*Lift ID:* {incident.lift.lift_identifier}\n"
                f"*Incident:* {incident.incident_type}\n"
                f"*Submitted:* {incident.report_submitted_at.strftime('%d-%b-%Y %I:%M %p')}\n\n"
                f"Awaiting JKR review."
            )
            send_telegram_message(message)

            return redirect('contractor_dashboard')
        else:
            print(f"Form errors for Incident ID {incident.id}: {form.errors}")
    else: # GET request
        form = ReportSubmissionForm(instance=incident)

    return render(request, 'lifts/submit_report_form.html', {'form': form, 'incident': incident})

# (Keep existing review_report function)
@login_required
def review_report(request, incident_id):
    incident = get_object_or_404(Incident, id=incident_id)
    if incident.status not in ['Pending Review', 'Correction Required', 'Resolved']:
         return redirect('contractor_dashboard')

    if request.method == 'POST':
        if 'approve' in request.POST:
            incident.report_acknowledged_by_jkr = True
            incident.status = 'Resolved'
            incident.report_requires_correction = False
            if not incident.time_resolved:
                incident.time_resolved = timezone.now()
            incident.save()
            print(f"Report Approved for Incident ID: {incident.id}")

            message = (
                f"👍 *Incident Report Approved* 👍\n\n"
                f"*Premise:* {incident.lift.premise_name}\n"
                f"*Lift ID:* {incident.lift.lift_identifier}\n"
                f"*Incident:* {incident.incident_type}\n"
                f"*Status:* Resolved"
            )
            send_telegram_message(message)

            return redirect('contractor_dashboard')

        elif 'request_correction' in request.POST:
            incident.report_requires_correction = True
            incident.status = 'Correction Required'
            incident.report_acknowledged_by_jkr = False
            incident.save()
            print(f"Correction Requested for Incident ID: {incident.id}")

            message = (
                f"⚠️ *Report Correction Required* ⚠️\n\n"
                f"*Premise:* {incident.lift.premise_name}\n"
                f"*Lift ID:* {incident.lift.lift_identifier}\n"
                f"*Incident:* {incident.incident_type}\n"
                f"*Action:* Please review and resubmit the report."
                 # Add correction notes: \n*Notes:* {request.POST.get('correction_notes')}"
            )
            send_telegram_message(message)

            return redirect('contractor_dashboard')

    # GET request
    return render(request, 'lifts/report_review.html', {'incident': incident})

@login_required # Protect this view
def view_report(request, incident_id):
    """Displays the details of a submitted and potentially resolved incident report."""
    incident = get_object_or_404(Incident, id=incident_id)

    # Ensure a report has actually been submitted for this incident
    if not incident.report_submitted_at:
        # Or redirect to contractor dashboard with a message?
        raise Http404("Report not yet submitted for this incident.")

    # Render a read-only template (we will create this next)
    return render(request, 'lifts/view_report.html', {'incident': incident})

# ==================================
# === JKR ANALYTICS DASHBOARD ====
# ==================================
@login_required
def jkr_analytics_dashboard(request):
    premise_name = "JKR Bahagian Perkhidmatan Mekanikal"
    
    # Get lifts at this premise, including contractor info
    # Assumes Lift model has a ForeignKey 'contractor'
    jkr_lifts = Lift.objects.filter(premise_name=premise_name).select_related('contractor')
    
    lift_reliability_data = []
    all_incidents_list = [] # For contractor performance calculation in JS

    # --- Calculate Lift Reliability (MTBF) ---
    for lift in jkr_lifts:
        # Get all incidents for this lift, ordered by time
        lift_incidents = Incident.objects.filter(lift=lift).order_by('timestamp')
        
        total_operational_time = timedelta(0)
        failure_count = 0
        last_timestamp = None

        # Approximate MTBF: Total time / number of failures
        # A more accurate calculation would need uptime logs, but this is an estimate.
        if lift_incidents.count() > 1:
            first_incident_time = lift_incidents.first().timestamp
            last_incident_time = lift_incidents.last().timestamp
            total_operational_time = last_incident_time - first_incident_time
            failure_count = lift_incidents.count() -1 # Number of intervals between failures

        mtbf_str = "N/A"
        if failure_count > 0 and total_operational_time.total_seconds() > 0:
            avg_seconds_between_failures = total_operational_time.total_seconds() / failure_count
            # Convert MTBF to days/hours for readability
            days, remainder = divmod(avg_seconds_between_failures, 86400)
            hours, _ = divmod(remainder, 3600)
            if days > 0:
                 mtbf_str = f"{int(days)}d {int(hours)}h"
            else:
                 mtbf_str = f"{int(hours)}h"
        elif lift_incidents.count() == 1:
             mtbf_str = "First Incident"
        elif lift_incidents.count() == 0:
             mtbf_str = "No Incidents"


        lift_reliability_data.append({
            'lift_identifier': lift.lift_identifier,
            'mtbf': mtbf_str,
            'total_incidents': lift_incidents.count(), # Also useful context
        })
        
        # --- Gather Incident Data for Contractor Analysis ---
        # Get relevant timestamps and contractor for MTTA/MTTR
        incidents_for_contractor = lift_incidents.filter(
            Q(time_attended__isnull=False) | Q(time_resolved__isnull=False) # Need at least one for calc
        ).values(
            'timestamp', # Detection time
            'time_attended', # Attendance time (for MTTA)
            'time_resolved', # Resolution time (for MTTR)
            contractor_name=F('lift__contractor__name') # Assumes Contractor model has 'name' field
        )
        all_incidents_list.extend(list(incidents_for_contractor))


    # Convert incident list to JSON for JavaScript
    incidents_json = json.dumps(all_incidents_list, cls=DjangoJSONEncoder)

    context = {
        'premise_name': premise_name,
        'lift_reliability': lift_reliability_data, # List of dicts with MTBF per lift
        'incidents_json': incidents_json,       # JSON string for JS charting
    }
    return render(request, 'lifts/jkr_analytics_dashboard.html', context)

# ==================================
# ========= FLUTTER API VIEWS ========
# ==================================

class IncidentListAPIView(APIView):
    """
    API view for the Flutter app to get a list of all incidents.
    Requires token authentication.
    """
    permission_classes = [IsAuthenticated] # Ensures user is logged in

    def get(self, request, *args, **kwargs):
        try:
            # Get all incidents, prefetch the related lift details for efficiency
            incidents = Incident.objects.all().select_related('lift', 'lift__contractor').order_by('-timestamp')

            # Use the serializer to convert the queryset to JSON-compatible data
            serializer = IncidentSerializer(incidents, many=True)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class LiftListAPIView(APIView):
    """
    API view for the Flutter app to get a list of all lifts (for the map).
    Requires token authentication.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            lifts = Lift.objects.all()
            serializer = LiftSerializer(lifts, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# lifts/views.py

# ... (keep all existing imports at the top) ...
# ... (keep all existing views like IncidentListAPIView, LiftHealthAPIView etc.) ...


# ==================================
# ======= CONTRACTOR API FOR FLUTTER APP =======
# ==================================

class ContractorDashboardAPIView(APIView):
    """
    API view for the Flutter app to get contractor-specific dashboard data:
    KPIs and the list of incidents requiring reports.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # ✅ CASE 1: Contractor user (linked)
        if hasattr(request.user, 'contractor') and request.user.contractor is not None:
            contractor = request.user.contractor
            lift_count = Lift.objects.filter(contractor=contractor).count()
            incident_count = Incident.objects.filter(lift__contractor=contractor).count()

            return Response({
                "role": "contractor",
                "contractor_name": contractor.name,
                "lift_count": lift_count,
                "incident_count": incident_count,
            }, status=status.HTTP_200_OK)

        # ✅ CASE 2: Admin / JKR / other user (not contractor)
        total_contractors = Contractor.objects.count()
        total_lifts = Lift.objects.count()
        total_incidents = Incident.objects.count()

        return Response({
            "role": "admin",
            "message": "Admin view: showing overall dashboard summary.",
            "total_contractors": total_contractors,
            "total_lifts": total_lifts,
            "total_incidents": total_incidents,
        }, status=status.HTTP_200_OK)

        contractor = request.user.contractor

        # ✅ 2. Build your response data
        data = {
            "contractor_name": contractor.name,
            "lift_count": contractor.lifts.count() if hasattr(contractor, 'lifts') else 0,
            # add other fields here
        }

        # 1. Fetch Incidents for this contractor
        # Only show incidents that need attention/reports
        incidents = Incident.objects.filter(
            lift__contractor=contractor,
            status__in=['Attended', 'Pending Review', 'Correction Required'] # Filter for relevant statuses
        ).select_related('lift', 'lift__contractor').order_by('-timestamp')

        # 2. Calculate KPIs (Report Submission On-Time, Reliability)
        total_reports_due = incidents.filter(report_due_date__isnull=False).count()
        on_time_reports = 0

        # For simplicity, calculate reliability based on average time to attend
        # This can be more complex based on specific SLA definitions
        total_time_to_attend_seconds = 0
        attended_incidents = Incident.objects.filter(
            lift__contractor=contractor,
            time_attended__isnull=False
        )
        attended_count = attended_incidents.count()

        for incident in incidents:
            if incident.report_submitted_on and incident.report_due_date:
                if incident.report_submitted_on <= incident.report_due_date:
                    on_time_reports += 1
            
            # For reliability, sum up time to attend
            if incident.time_attended and incident.timestamp:
                 total_time_to_attend_seconds += (incident.time_attended - incident.timestamp).total_seconds()


        report_submission_on_time_percentage = 0
        if total_reports_due > 0:
            report_submission_on_time_percentage = round((on_time_reports / total_reports_due) * 100)

        # This is a simplified reliability; in real life, it's more complex
        # Here, we'll just say "Good" if avg time to attend < 24 hours (86400s)
        contractor_reliability_percentage = 100 # Default to high
        if attended_count > 0:
            avg_time_to_attend = total_time_to_attend_seconds / attended_count
            if avg_time_to_attend > 86400: # If avg is more than 24 hours
                contractor_reliability_percentage = 80 # Just an example
            if avg_time_to_attend > (86400 * 2): # If avg is more than 48 hours
                contractor_reliability_percentage = 60 # Just an example

        # 3. Serialize incidents
        incident_serializer = IncidentSerializer(incidents, many=True)

        response_data = {
            'report_submission_on_time_percentage': report_submission_on_time_percentage,
            'contractor_reliability_percentage': contractor_reliability_percentage,
            'incidents_requiring_report': incident_serializer.data,
        }
        return Response(response_data, status=status.HTTP_200_OK)


class SubmitReportAPIView(APIView):
    """
    API endpoint for a contractor to submit a report for an incident.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, incident_id, *args, **kwargs):
        try:
            incident = get_object_or_404(Incident, id=incident_id)

            # Ensure the user (contractor) is assigned to this lift's contractor
            try:
                user_contractor = request.user.contractor
            except Contractor.DoesNotExist:
                return Response(
                    {'error': 'User is not associated with a contractor.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if incident.lift.contractor != user_contractor:
                return Response(
                    {'error': 'You do not have permission to submit a report for this incident.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Only allow submission if status is appropriate
            if incident.status not in ['Attended', 'Pending Review', 'Correction Required']:
                return Response(
                    {'error': f'Report cannot be submitted for incident in "{incident.status}" status.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Simulate report submission: Update incident status and timestamp
            incident.status = 'Report Submitted'
            incident.report_submitted_on = timezone.now()
            # If report was pending review/correction, it's now 'Review Acknowledged'
            # if incident.status == 'Pending Review' or incident.status == 'Correction Required':
            #     incident.status = 'Review Acknowledged' # Or another appropriate status
            incident.save()

            # Optional: Send Telegram notification
            try:
                message = (
                    f"📝 *Report Submitted (Mobile App)* 📝\n\n"
                    f"*Premise:* {incident.lift.premise_name}\n"
                    f"*Lift ID:* {incident.lift.lift_identifier}\n"
                    f"*Incident:* {incident.incident_type}\n"
                    f"*Submitted By:* {request.user.username} ({user_contractor.name})\n"
                    f"*Time Submitted:* {timezone.localtime(incident.report_submitted_on).strftime('%d-%b-%Y %I:%M %p')}"
                )
                send_telegram_message(message)
            except Exception as e:
                print(f"[ERROR] Failed to send 'Report Submitted' Telegram alert: {e}")

            serializer = IncidentSerializer(incident)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Http404:
            return Response({'error': 'Incident not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_report_api(request):
    """
    Flutter API endpoint to submit an incident investigation report.
    Expects JSON body containing:
    {
      "incident_id": 1,
      "direct_cause": "...",
      "rc_machine": "...",
      "rc_method": "...",
      "rc_man": "...",
      "rc_material": "...",
      "corrective_action": "...",
      "permanent_action": "...",
      "contractor_acknowledgement": true
    }
    """
    try:
        incident_id = request.data.get("incident_id")
        incident = Incident.objects.get(id=incident_id)
    except Incident.DoesNotExist:
        return Response({"error": "Incident not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = IncidentReportSerializer(incident, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        incident.status = "Pending Review"
        incident.report_submitted_at = timezone.now()
        incident.save()
        return Response({"message": "Report submitted successfully."}, status=status.HTTP_200_OK)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([AllowAny])
def view_report_api(request, incident_id):
    """
    JSON API for mobile app to retrieve a detailed incident report.
    Compatible with the actual Incident model structure.
    """
    from .models import Incident, Lift

    try:
        incident = get_object_or_404(Incident, id=incident_id)
        lift = incident.lift

        data = {
            "incident_id": incident.id,
            "premise_name": getattr(lift, 'premise_name', 'N/A'),
            "lift_identifier": getattr(lift, 'lift_identifier', 'N/A'),
            "contractor": str(getattr(lift.contractor, 'name', 'N/A')),
            "incident_type": incident.incident_type or "N/A",
            "status": incident.status or "N/A",
            "timestamp": incident.timestamp.strftime("%d %B %Y, %I:%M %p") if incident.timestamp else "N/A",
            "time_attended": incident.time_attended.strftime("%d %B %Y, %I:%M %p") if incident.time_attended else "N/A",
            "time_resolved": incident.time_resolved.strftime("%d %B %Y, %I:%M %p") if incident.time_resolved else "N/A",
            "report_submitted_at": incident.report_submitted_at.strftime("%d %B %Y, %I:%M %p")
                if incident.report_submitted_at else "Not yet submitted",

            # 🔹 Section B: Incident Description
            "symptom": incident.symptom or "N/A",
            "direct_cause": incident.direct_cause or "N/A",

            # 🔹 Section C: Root Cause Analysis (4M)
            "rc_method": incident.rc_method or "N/A",
            "rc_man": incident.rc_man or "N/A",
            "rc_material": incident.rc_material or "N/A",
            "rc_machine": incident.rc_machine or "N/A",

            # 🔹 Section D: Corrective & Permanent Actions
            "corrective_action": incident.corrective_action or "N/A",
            "permanent_action": incident.permanent_action or "N/A",

            # 🔹 File proofs (if any)
            "rc_proof": incident.rc_proof.url if incident.rc_proof else None,
            "corrective_action_proof": incident.corrective_action_proof.url if incident.corrective_action_proof else None,
            "permanent_action_proof": incident.permanent_action_proof.url if incident.permanent_action_proof else None,

            # 🔹 Status flags
            "contractor_acknowledgement": incident.contractor_acknowledgement,
            "report_acknowledged_by_jkr": incident.report_acknowledged_by_jkr,
            "report_requires_correction": incident.report_requires_correction,
        }

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"[ERROR] view_report_api failed: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lift_health_view(request, pk):
    """Lift health for the mobile app. Returns the latest REAL SensorReading for
    the lift (no simulation). Response shape is kept backward-compatible."""
    from rest_framework import status as drf_status

    lift = get_object_or_404(Lift, pk=pk)
    reading = SensorReading.objects.filter(lift=lift).order_by('-created_at').first()

    base = {
        "lift_id": lift.id,
        "lift_identifier": lift.lift_identifier,
        "premise": lift.premise_name,
    }

    if reading is None:
        base.update({
            "has_data": False,
            "status": "No Data",
            "predicted": "-",
            "confidence": 0.0,
            "sensor_readings": {},
            "timestamp": None,
        })
        return Response(base, status=drf_status.HTTP_200_OK)

    is_ok = (reading.prediction or "").strip().lower() in ("no failure", "normal", "healthy", "")
    labels = {
        "feature_p1": "Control Panel Temp (°K)", "feature_p2": "Motor Temperature (°K)",
        "feature_p3": "Motor Speed (RPM)", "feature_s1": "Motor Torque (Nm)",
        "feature_s2": "Operational Hours (h)", "feature_s3": "Feature S3",
        "vibration": "Vibration (mm/s²)", "vertical_acceleration_mps2": "Car Acceleration (m/s²)",
        "acoustic_db": "Acoustic Level (dB)",
    }
    base.update({
        "has_data": True,
        "status": "Normal Operation" if is_ok else "Failure Warning",
        "predicted": reading.prediction or "-",
        "confidence": round(reading.confidence, 2),
        "sensor_readings": {labels[f]: round(getattr(reading, f), 2) for f in SensorReading.FEATURES},
        "timestamp": reading.created_at.isoformat(),
    })
    return Response(base, status=drf_status.HTTP_200_OK)

#@api_view(['GET'])
#@permission_classes([AllowAny])
#def lift_analytics_view(request, role):
    """
    Returns detailed analytics for lifts and contractors.
    Used by mobile analytics dashboard.
    """

    # --- 1. Total lifts ---
#    total_lifts = Lift.objects.count()

    # --- 2. Active incidents (Detected or Attended) ---
#    active_incidents = Incident.objects.filter(status__in=['Detected', 'Attended']).count()

    # --- 3. Resolved incidents ---
#    resolved_incidents = Incident.objects.filter(status='Resolved').count()

    # --- 4. Uptime percentage (example simulation) ---
    # Adjust logic if you have actual downtime tracking
#    uptime_percentage = 100.0 - (active_incidents / total_lifts * 100 if total_lifts > 0 else 0)

    # --- 5. Average response time (MTTA) ---
#    attended_incidents = Incident.objects.filter(time_attended__isnull=False)
#    total_response_time = timedelta()
#    for inc in attended_incidents:
#        total_response_time += (inc.time_attended - inc.timestamp)
#    avg_response_hours = (
#        total_response_time.total_seconds() / 3600 / attended_incidents.count()
#        if attended_incidents.count() > 0 else 0
#    )

    # --- 6. Weekly trend (past 7 days) ---
#    today = timezone.now().date()
#    trend_labels = []
#    trend_values = []
#    for i in range(6, -1, -1):  # 7 days back
#        day = today - timedelta(days=i)
#        count = Incident.objects.filter(timestamp__date=day).count()
#        trend_labels.append(day.strftime("%a"))  # Mon, Tue, etc.
#        trend_values.append(count)

#    data = {
#        "total_lifts": total_lifts,
#        "active_incidents": active_incidents,
#        "resolved_incidents": resolved_incidents,
#        "uptime_percentage": round(uptime_percentage, 2),
#        "avg_response_time": round(avg_response_hours, 2),
#        "incident_trend": trend_values,
#        "labels": trend_labels,
#    }

#    return Response(data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def lift_analytics_full_api(request):
    """
    Mobile API version of JKR Analytics Dashboard.
    Returns contractor performance (MTTA / MTTR)
    and lift reliability (MTBF) in JSON format.
    """

    from django.db.models import Avg, F, ExpressionWrapper, DurationField
    from .models import Lift, Incident, Contractor   # ✅ Correct import

    # ====== Contractor Performance (MTTA / MTTR) ======
    contractor_stats = {}

    # Mean Time To Attend (MTTA)
    mtta_results = (
        Incident.objects
        .exclude(time_attended__isnull=True)
        .values("lift__contractor__name")
        .annotate(
            mtta_hours=Avg(
                ExpressionWrapper(
                    F("time_attended") - F("timestamp"),
                    output_field=DurationField()
                )
            )
        )
    )

    # Mean Time To Repair (MTTR)
    mttr_results = (
        Incident.objects
        .exclude(time_resolved__isnull=True)
        .values("lift__contractor__name")
        .annotate(
            mttr_hours=Avg(
                ExpressionWrapper(
                    F("time_resolved") - F("timestamp"),
                    output_field=DurationField()
                )
            )
        )
    )

    # Combine both per contractor
    for row in mtta_results:
        name = row["lift__contractor__name"] or "Unknown Contractor"
        contractor_stats.setdefault(name, {})["mtta"] = (
            round(row["mtta_hours"].total_seconds() / 3600, 3)
            if row["mtta_hours"] else 0
        )

    for row in mttr_results:
        name = row["lift__contractor__name"] or "Unknown Contractor"
        contractor_stats.setdefault(name, {})["mttr"] = (
            round(row["mttr_hours"].total_seconds() / 3600, 3)
            if row["mttr_hours"] else 0
        )

    # ====== Lift Reliability (MTBF) ======
    lift_reliability = []
    for lift in Lift.objects.all():
        incidents = Incident.objects.filter(lift=lift).order_by("timestamp")
        if incidents.count() == 0:
            mtbf_display = "No Incidents"
        else:
            if incidents.count() == 1:
                mtbf_display = "First Incident"
            else:
                total_time = incidents.last().timestamp - incidents.first().timestamp
                avg_gap_hours = total_time.total_seconds() / 3600 / (incidents.count() - 1)
                mtbf_display = f"{round(avg_gap_hours, 1)}h"

        lift_reliability.append({
            "lift_identifier": lift.lift_identifier,
            "total_incidents": incidents.count(),
            "mtbf": mtbf_display,
        })

    # ====== Final API Response ======
    return Response({
        "contractor_stats": contractor_stats,
        "lift_reliability": lift_reliability,
    })
