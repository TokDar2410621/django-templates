from django.urls import path

from . import views

app_name = "realtime_messaging"

urlpatterns = [
    path("conversations/", views.ConversationsView.as_view(), name="conversations"),
    path("conversations/<str:conv_id>/messages/", views.MessagesView.as_view(), name="messages"),
    path("conversations/<str:conv_id>/read/", views.MarkReadView.as_view(), name="read"),
    path("messages/<str:msg_id>/", views.MessageView.as_view(), name="message"),
    path("messages/<str:msg_id>/reaction/", views.ReactionView.as_view(), name="reaction"),
    path("blocks/", views.BlocksView.as_view(), name="blocks"),
]
