"""HTTP routes for the quiz UI."""
from django.urls import path
from . import views

app_name = "quiz"

urlpatterns = [
    path("", views.home, name="home"),
    path("play/", views.join, name="join"),
    path("player/<int:player_id>/", views.player, name="player"),
    path("host/<uuid:host_token>/", views.host, name="host"),
    path("api/join/", views.join_submit, name="join_submit"),
]
