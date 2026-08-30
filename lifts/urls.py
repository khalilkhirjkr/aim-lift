# lifts/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Keep-alive / health check (used by external uptime pinger)
    path('healthz/', views.healthz, name='healthz'),

    # Public landing page
    path('', views.landing, name='landing'),

    # Dashboards
    path('dashboard/', views.incident_list, name='incident_list'),
    path('contractor/', views.contractor_dashboard, name='contractor_dashboard'),
    path('health/', views.lift_health_dashboard, name='lift_health'),
    path('analytics/jkr/', views.jkr_analytics_dashboard, name='jkr_analytics_dashboard'),

    # API endpoints for ESP32 (Alerts)
    path('api/iot/alert/', views.handle_alert, name='handle_alert'),
    path('api/iot/check_status/', views.check_status, name='check_status'),
    
    # Report Workflow
    path('report/submit/<int:incident_id>/', views.submit_report_form, name='submit_report'),
    path('review/<int:incident_id>/', views.review_report, name='review_report'),
    path('report/view/<int:incident_id>/', views.view_report, name='view_report'),

    # Simulation for Presentation
    path('load_future_data/', views.load_future_data, name='load_future_data'),

    # API endpoint for mobile app report submission
    path('api/submit_report/', views.submit_report_api, name='submit_report_api'),

]