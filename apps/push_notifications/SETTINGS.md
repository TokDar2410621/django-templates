# push-notifications : integration

## 1. Dependances

```
pip install djangorestframework "pywebpush>=2.0" "httpx[http2]" pyjwt cryptography google-auth
```

## 2. INSTALLED_APPS et URLs

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "push_notifications",
]

# urls.py
path("api/push/", include("push_notifications.urls")),
```

Puis `python manage.py migrate push_notifications`.

## 3. Reglages (tous optionnels : un fournisseur sans ses cles est ignore)

Les valeurs viennent des variables d'environnement. Jamais une cle dans le code ni dans git.

```python
import os

# Navigateur (Web Push). Generer une fois : python manage.py generer_cles_vapid
PUSH_VAPID_PUBLIC_KEY = os.environ.get("PUSH_VAPID_PUBLIC_KEY", "")
PUSH_VAPID_PRIVATE_KEY = os.environ.get("PUSH_VAPID_PRIVATE_KEY", "")  # brute, PEM, ou PEM sur une ligne
PUSH_VAPID_CONTACT = os.environ.get("PUSH_VAPID_CONTACT", "")          # un courriel ou une URL https

# Android, et iPhone si l'appli utilise Firebase.
# Console Firebase > Parametres du projet > Comptes de service > Generer une nouvelle cle privee.
# Le CONTENU du JSON, ou le chemin du fichier. Il doit venir du MEME projet que l'appli.
PUSH_FCM_CREDENTIALS = os.environ.get("PUSH_FCM_CREDENTIALS", "")
PUSH_FCM_PROJECT_ID = os.environ.get("PUSH_FCM_PROJECT_ID", "")  # facultatif : lu dans le JSON sinon

# iPhone sans Firebase. Apple Developer > Keys > cle APNs (.p8).
PUSH_APNS_TEAM_ID = os.environ.get("PUSH_APNS_TEAM_ID", "")
PUSH_APNS_KEY_ID = os.environ.get("PUSH_APNS_KEY_ID", "")
PUSH_APNS_AUTH_KEY = os.environ.get("PUSH_APNS_AUTH_KEY", "")    # contenu du .p8, \n litteraux acceptes
PUSH_APNS_BUNDLE_ID = os.environ.get("PUSH_APNS_BUNDLE_ID", "")  # ex. com.entreprise.appli

# Expo : rien d'obligatoire. Si la securite renforcee est activee chez Expo :
PUSH_EXPO_ACCESS_TOKEN = os.environ.get("PUSH_EXPO_ACCESS_TOKEN", "")
```

Changer les cles VAPID plus tard invalide tous les abonnements des navigateurs
(`examples/abonnement-web.js` les refait a la visite suivante).

## 4. Brancher les clients

- Site : servir `examples/sw.js` a la racine (`/sw.js`), appeler `activerNotifications()` de `examples/abonnement-web.js` depuis un bouton.
- Appli mobile : `examples/mobile.md`, et `examples/flutter/FLUTTER.md` pour Flutter.

## 5. Verifier

```
pytest apps/push_notifications/tests/
```

Puis, connecte dans l'appli ou sur le site : `POST /api/push/test/`.
