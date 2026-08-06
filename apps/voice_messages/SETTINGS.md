# voice_messages : integration

## 1. Dependances

```
pip install djangorestframework
```

## 2. INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "voice_messages",
]
```

## 3. Reglages (tous optionnels, defauts sains)

```python
VOICE_MESSAGES_ALLOWED_TYPES = ("audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/aac", "audio/wav")
VOICE_MESSAGES_MAX_BYTES = 10 * 1024 * 1024
VOICE_MESSAGES_MAX_SECONDS = 300
```

Stockage : `FileField` standard, donc `default_storage`. Avec le snippet
`storage_s3_autoswitch.py`, les notes partent sur S3 des que les variables
sont posees ; rien a changer ici.

## 4. URLs

```python
path("api/voice/", include("voice_messages.urls")),
```

## 5. Migration et tests

```
python manage.py migrate voice_messages
pytest apps/voice_messages/tests/
```

## 6. Durcissement optionnel par projet

- Verifier la duree cote serveur : `ffprobe -show_entries format=duration`
  sur le fichier recu, et refuser si l'ecart avec `duration_seconds` depasse
  ta tolerance.
- Antivirus/inspection : brancher ta moulinette existante sur `post_save`.
- Quota par utilisateur : compter `VoiceMessage.objects.filter(sender=...)`
  dans un service maison avant d'appeler `enregistrer`.
