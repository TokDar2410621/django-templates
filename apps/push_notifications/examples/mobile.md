# Brancher l'appli mobile

L'appli récupère le jeton push de l'appareil et l'envoie au serveur une fois l'utilisateur connecté, puis à chaque changement du jeton :

```
POST /api/push/appareils/
{"kind": "fcm", "token": "<jeton>"}
```

Avec l'authentification habituelle de ton API (JWT, jeton…). À la déconnexion : `DELETE /api/push/appareils/` avec `{"token": "<jeton>"}`.

## Selon la technologie de l'appli

| Appli | Jeton | Corps à envoyer |
|---|---|---|
| Flutter avec `firebase_messaging` (code complet : `flutter/FLUTTER.md`) | `await FirebaseMessaging.instance.getToken()` | `{"kind": "fcm", "token": ...}` |
| React Native avec `@react-native-firebase/messaging` | `await messaging().getToken()` | `{"kind": "fcm", "token": ...}` |
| Expo | `(await Notifications.getExpoPushTokenAsync({ projectId })).data` | `{"kind": "expo", "token": ...}` |
| iPhone natif (Swift) sans Firebase | `didRegisterForRemoteNotificationsWithDeviceToken`, converti en hexadécimal | `{"kind": "apns", "token": ..., "sandbox": true}` en debug, `false` sinon |

Le jeton change de temps en temps : écoute son rafraîchissement (`onTokenRefresh` avec Firebase) et renvoie-le.

## Les oublis classiques côté appli

- **Android 13 et plus** : l'appli doit demander la permission `POST_NOTIFICATIONS` à l'utilisateur. Sans elle, rien ne s'affiche, et aucune erreur n'apparaît nulle part.
- **iPhone avec Firebase** : la clé APNs (.p8) doit être téléversée dans la console Firebase (Paramètres du projet, Cloud Messaging, configuration de l'appli Apple). Sans elle, Android reçoit et l'iPhone ne reçoit rien.
- **iPhone** : dans Xcode, les capacités « Push Notifications » et « Background Modes, Remote notifications » doivent être cochées.
- **iPhone sans Firebase** : un build lancé depuis Xcode utilise le serveur sandbox d'Apple ; TestFlight et l'App Store, le serveur de production. Le template bascule tout seul sur `BadDeviceToken`.

## Tester en un appel

Une fois connecté dans l'appli ou sur le site : `POST /api/push/test/`. La réponse dit, appareil par appareil, si le fournisseur a accepté le push, et sinon pourquoi (`last_error`).
