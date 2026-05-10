"""WebSocket routes."""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/host/(?P<host_token>[0-9a-f-]+)/$", consumers.HostConsumer.as_asgi()),
    re_path(r"ws/player/(?P<player_id>\d+)/$", consumers.PlayerConsumer.as_asgi()),
]
