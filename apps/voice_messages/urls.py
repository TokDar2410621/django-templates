from django.urls import path

from . import views

app_name = "voice_messages"

urlpatterns = [
    path("upload/", views.UploadView.as_view(), name="upload"),
    path("<uuid:note_uuid>/", views.DetailView.as_view(), name="detail"),
]
