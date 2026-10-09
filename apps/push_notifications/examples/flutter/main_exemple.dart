// Exemple de branchement dans main.dart. Adapte les noms à ton appli.

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import 'firebase_options.dart';
import 'push_service.dart';

final navigatorKey = GlobalKey<NavigatorState>();
final messagerKey = GlobalKey<ScaffoldMessengerState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  // A enregistrer AVANT runApp.
  FirebaseMessaging.onBackgroundMessage(gestionnaireArrierePlan);
  runApp(MaterialApp(
    navigatorKey: navigatorKey,
    scaffoldMessengerKey: messagerKey,
    home: const Placeholder(),
  ));
}

/// A appeler juste après une connexion réussie.
Future<PushService> brancherPush(String jwt) async {
  final push = PushService(
    apiBase: 'https://api.ton-site.com/api/push',
    enteteAuthorization: () async => 'Bearer $jwt',
    ouvrirUrl: (url) => navigatorKey.currentState?.pushNamed(url),
    auPremierPlan: (message) => messagerKey.currentState?.showSnackBar(
      SnackBar(content: Text(message.notification?.title ?? 'Nouvelle notification')),
    ),
  );
  await push.activer();
  return push;
}

// A la déconnexion : await push.desactiver(); puis oublie le JWT.
