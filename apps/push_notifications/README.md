# push-notifications

═════════════════════════════════════════════
Template : push-notifications
Version  : 1.0.0
Mode     : EXTRACT-B
Source   : planner/services/apns.py (APNs, lecons de production) + notifications-multichannel (Web Push), le reste ecrit pour ce template
Stack    : Django 5+ / DRF / pywebpush / httpx (HTTP/2) / PyJWT / google-auth
Deps     : `djangorestframework`, `pywebpush>=2.0`, `httpx[http2]`, `pyjwt`, `cryptography`, `google-auth`
Used by  : (vide)
═════════════════════════════════════════════

Notifications push vers tous les appareils d'un utilisateur, en un appel :
ses navigateurs (Web Push), son Android et son iPhone (Firebase), son iPhone
en direct chez Apple (APNs), ou son appli Expo. Les appareils morts se
suppriment tout seuls, chaque erreur est notee sur l'appareil concerne, et
`POST /api/push/test/` dit appareil par appareil pourquoi un push n'est pas
parti.

Difference avec `notifications-multichannel` : celui-ci couvre courriel, SMS
et Web Push seulement. Ce template couvre le push mobile, et se monte seul ou
a cote.

## Envoyer

```python
from push_notifications.services import send_push

resultat = send_push(user, "Nouvelle commande", "Commande #42 recue", url="/commandes/42", data={"id": 42})
# resultat.delivered, resultat.removed, resultat.failed, resultat.skipped, resultat.errors
```

`send_push` ne leve jamais. Un appel HTTP par appareil : depuis une vue tres
frequentee, le lancer dans une tache de fond.

## Endpoints

    GET    cle-vapid/      la cle publique VAPID (sans authentification)
    POST   appareils/      navigateur : {"kind": "web", "subscription": <subscription.toJSON()>}
                           mobile     : {"kind": "fcm" | "apns" | "expo", "token": "...", "sandbox": false}
    DELETE appareils/      {"token": "<jeton ou endpoint>"}
    POST   test/           push de test a soi-meme + etat de chaque appareil

Les vues utilisent l'authentification DRF du projet (session, JWT, jeton).

## Fournisseurs

| `kind` | Pour | Cle(s) serveur |
|---|---|---|
| `web` | Chrome, Firefox, Edge, Safari, PWA sur iPhone | `PUSH_VAPID_*` |
| `fcm` | Android, et iPhone si l'appli utilise le SDK Firebase (Flutter, React Native Firebase) | `PUSH_FCM_CREDENTIALS` |
| `apns` | iPhone sans Firebase (Swift natif) | `PUSH_APNS_*` |
| `expo` | Appli React Native Expo | aucune (`PUSH_EXPO_ACCESS_TOKEN` en option) |

Un fournisseur sans ses cles est ignore (`skipped`), jamais en erreur.

## Clients (`examples/`)

- `sw.js` et `abonnement-web.js` : le service worker du site et l'abonnement du navigateur (refait l'abonnement si les cles VAPID ont change).
- `mobile.md` : quel jeton recuperer selon la technologie de l'appli.
- `flutter/` : `push_service.dart` pret a copier (permission, jeton Apple sur iPhone, rafraichissement du jeton, ouverture de la bonne page au toucher) et `FLUTTER.md`. Ecrit d'apres la documentation officielle de `firebase_messaging`, pas compile dans ce repo.

## Pieges que le template evite (et qui cassent un push sans erreur visible)

- **Ancienne API Firebase** (cle serveur, `fcm/send`) : depreciee le 20 juin 2023, fermeture commencee le 22 juillet 2024. Le template utilise l'API HTTP v1 avec un compte de service.
- **Cle VAPID PEM** : pywebpush la refuse en texte ("Could not deserialize key data"). `cles.private_key_for_pywebpush` accepte brute, PEM, et PEM sur une ligne avec des `\n` litteraux.
- **`vapid_claims` partage** : pywebpush y ecrit l'adresse du premier service de push (`aud`) ; reutilise, les autres navigateurs repondent 403. Dictionnaire neuf a chaque envoi.
- **`data` non texte** : Firebase repond 400. Tout est converti en chaine.
- **Jetons morts** : supprimes sur 404/410 (Web Push), `UNREGISTERED` et `SENDER_ID_MISMATCH` (Firebase), 410 et `BadDeviceToken` (Apple), `DeviceNotRegistered` (Expo). Un 400 Firebase, qui peut venir du message, ne supprime jamais l'appareil.
- **Apple sandbox et production** : sur `BadDeviceToken`, un essai en sandbox (build Xcode), retenu ensuite.
- **Jeton fournisseur Apple** : garde 50 minutes (Apple refuse plus de 60 minutes, et un renouvellement plus d'une fois par 20 minutes).

## Tests

    pytest apps/push_notifications/tests/

39 tests. Le Web Push est teste sans aucun mock : un serveur local joue le
service de push, le message est reellement chiffre, puis dechiffre avec la cle
de l'abonne, et la signature VAPID est verifiee, pour les trois formats de
cle. Firebase, Apple et Expo sont testes jusqu'a la requete (format exact,
jeton Apple signe et verifie, traitement de chaque reponse) contre des
serveurs simules. La livraison sur un vrai telephone exige les cles d'un
projet reel : `POST /api/push/test/` la verifie en conditions reelles.
