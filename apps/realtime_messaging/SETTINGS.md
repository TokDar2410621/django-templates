# realtime_messaging : integration

## 1. Dependances

```
pip install channels redis djangorestframework djangorestframework-simplejwt
```

(`channels-redis` en plus si tu veux le direct multi-processus en prod.)

## 2. INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "channels",            # optionnel mais recommande (asgi + layers)
    "realtime_messaging",
]
```

## 3. Reglages (tous optionnels, defauts sains)

```python
REALTIME_MESSAGING_REDIS_URL = env("REDIS_URL")   # sinon REDIS_EPHEMERAL_URL puis REDIS_URL
REALTIME_MESSAGING_TTL_SECONDS = 7 * 24 * 3600     # duree de vie d'un message
```

Sans aucune URL Redis : l'app monte, migre, et ses endpoints repondent 503
« dormant » (le meme langage que la vitrine de la librairie).

## 4. URLs

```python
path("api/messaging/", include("realtime_messaging.urls")),
```

## 5. WebSocket (prod temps reel)

```python
# config/asgi.py
from channels.routing import ProtocolTypeRouter, URLRouter
from realtime_messaging.middleware import JWTAuthMiddleware
from realtime_messaging.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
})

# settings.py : layer partage entre workers
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL")]},
    }
}
```

Sans ASGI ni layer, tout le REST fonctionne ; seul le push live est absent
(les broadcasts deviennent des no-ops silencieux).

## 6. Migration et tests

```
python manage.py migrate realtime_messaging
pytest apps/realtime_messaging/tests/
```

## 7. Integration declaree avec voice_messages

Pour un message vocal : uploader via `voice_messages` (POST /api/voice/upload/)
puis poster ici `{"msg_type": "audio", "content": "<url>", "duration": <s>}`.
Aucun import croise entre les deux apps.
