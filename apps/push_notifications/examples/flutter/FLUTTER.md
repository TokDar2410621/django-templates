# Le push dans une appli Flutter

Avec Flutter, Android et iPhone passent tous les deux par Firebase : l'appli envoie son jeton au serveur avec `"kind": "fcm"`, et le template Django push_notifications s'occupe du reste.

Deux fichiers à copier dans `lib/` : `push_service.dart` (tout le travail) et `main_exemple.dart` (le branchement, à adapter).

Ces fichiers suivent la documentation officielle de `firebase_messaging`, mais je ne les ai pas compilés : il n'y avait pas de Flutter sur la machine qui les a écrits. Lance `flutter analyze` après les avoir copiés.

## 1. Mettre en place (une fois)

1. **Firebase** : dans la console Firebase, ouvre le projet (ou crée-le), puis dans l'appli : `dart pub global activate flutterfire_cli` et `flutterfire configure`. Cela génère `lib/firebase_options.dart`.
2. **Dépendances** : `flutter pub add firebase_core firebase_messaging http`
3. **Android** : `compileSdk` et `targetSdk` à 33 ou plus dans `android/app/build.gradle`. Teste sur un appareil ou un émulateur avec les services Google Play.
4. **iPhone** :
   - Xcode, cible Runner, « Signing & Capabilities » : ajoute « Push Notifications » et « Background Modes », case « Remote notifications ».
   - Compte Apple Developer, « Keys » : crée une clé APNs (fichier .p8), note son Key ID et ton Team ID.
   - Console Firebase, Paramètres du projet, Cloud Messaging, configuration de l'appli Apple : téléverse la clé .p8 avec ces deux identifiants.
   - Teste sur un vrai iPhone.
5. **Serveur** : `PUSH_FCM_CREDENTIALS` doit venir du MÊME projet Firebase que l'appli. Sinon Firebase répond `SENDER_ID_MISMATCH` et le template supprime l'appareil.

## 2. Brancher

```dart
// main.dart, avant runApp :
FirebaseMessaging.onBackgroundMessage(gestionnaireArrierePlan);

// Après la connexion :
final push = PushService(
  apiBase: 'https://api.ton-site.com/api/push',
  enteteAuthorization: () async => 'Bearer $jwt',
  ouvrirUrl: (url) => navigatorKey.currentState?.pushNamed(url),
);
await push.activer();

// À la déconnexion :
await push.desactiver();
```

`activer()` demande la permission, attend le jeton Apple sur iPhone, envoie le jeton Firebase au serveur, le renvoie à chaque changement, et ouvre la bonne page quand l'utilisateur touche une notification (le champ `url` du push).

## 3. Tester

1. Connecte-toi dans l'appli, puis mets-la en arrière-plan.
2. Appelle `POST /api/push/test/` avec le même compte : la notification doit apparaître.
3. Si elle n'apparaît pas, la réponse dit pourquoi, appareil par appareil (`last_error`).

## 4. Quand ça ne marche pas

| Symptôme | Cause | Correction |
|---|---|---|
| Rien sur Android 13 ou plus | Permission jamais demandée, ou `targetSdk` sous 33. | `activer()` la demande ; `targetSdk` à 33 ou plus. |
| Sur iPhone, `getToken()` échoue (`apns-token-not-set`) | Le jeton Apple n'est pas encore arrivé. | `activer()` l'attend jusqu'à 10 secondes. S'il n'arrive jamais : simulateur, ou capacité « Push Notifications » absente. |
| Android reçoit, l'iPhone non | Clé .p8 non téléversée dans Firebase, ou capacités Xcode manquantes. | Section 1, point 4. |
| Rien quand l'appli est ouverte, sur Android | Comportement normal : le système n'affiche pas les push d'une appli au premier plan. | Le rappel `auPremierPlan` (un SnackBar dans `main_exemple.dart`), ou le paquet `flutter_local_notifications`. |
| Le gestionnaire d'arrière-plan marche en debug mais pas en release | Ce n'est pas une fonction de premier niveau, ou il manque `@pragma('vm:entry-point')`. | Garde `gestionnaireArrierePlan` tel quel. |
| L'appareil disparaît du serveur après le premier envoi | Firebase a répondu `UNREGISTERED` ou `SENDER_ID_MISMATCH` : jeton périmé, ou compte de service d'un autre projet. | Section 1, point 5. |
| Après une déconnexion, l'ancien compte reçoit encore les push | `desactiver()` n'est pas appelée. | L'appeler à la déconnexion, avant d'oublier le JWT. |
