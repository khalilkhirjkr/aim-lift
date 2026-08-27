# lifts/api_urls.py
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from . import views
from .views import lift_health_view, lift_analytics_full_api


app_name = 'lifts_api' # Use a distinct app_name for the API

urlpatterns = [
    # JWT Authentication URLs
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'), # This is your login endpoint
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # Add other API endpoints here later (e.g., incidents, lifts)
    path('incidents/', views.IncidentListAPIView.as_view(), name='api-incident-list'),
    path('lifts/', views.LiftListAPIView.as_view(), name='api-lift-list'),

    # CONTRACTOR DASHBOARD
    path('contractor/dashboard/', views.ContractorDashboardAPIView.as_view(), name='api-contractor-dashboard'),
    path('contractor/incidents/<int:incident_id>/submit-report/', views.SubmitReportAPIView.as_view(), name='api-submit-report'),
    path('report/view/<int:incident_id>/', views.view_report_api, name='view_report_api'),

    # HEALTH DASHBOARD
    path('lifts/<int:pk>/health/', lift_health_view, name='lift-health'),

    # LIFT ANALYTICS
    # path('analytics/<str:role>/', lift_analytics_view, name='lift_analytics'),
    path('analytics/full/', lift_analytics_full_api, name='lift_analytics_full_api'),
]