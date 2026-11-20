from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/catalogue", views.catalogue),
    path("api/enquiries", views.enquiries),
    path("api/enquiries/<int:enquiry_id>/sessions", views.start),
    path("api/sessions", views.sessions),
    path("api/sessions/<int:session_id>/turns", views.turn),
    path("api/speech", views.speech),
    path("api/client-log", views.client_log),
]
