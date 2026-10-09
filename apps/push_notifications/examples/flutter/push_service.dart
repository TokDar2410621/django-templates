// Notifications push dans une appli Flutter, branchées sur le template Django push_notifications.
//
// Dépendances : flutter pub add firebase_core firebase_messaging http
// Préalable   : flutterfire configure (génère lib/firebase_options.dart)
// Mode d'emploi complet : FLUTTER.md, dans ce dossier.

import 'dart:async';
import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'firebase_options.dart';

/// Appelé quand un push arrive appli en arrière-plan ou fermée.
/// Fonction de premier niveau avec @pragma('vm:entry-point') : une méthode de
/// classe, ou l'oubli du pragma, et elle n'est jamais appelée en mode release.
@pragma('vm:entry-point')
Future<void> gestionnaireArrierePlan(RemoteMessage message) async {
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  // Le système affiche la notification tout seul : rien à faire pour un simple affichage.
}

class PushService {
  PushService({
    required this.apiBase,
    required this.enteteAuthorization,
    required this.ouvrirUrl,
    this.auPremierPlan,
  });

  /// Le préfixe des routes du template, ex. https://api.ton-site.com/api/push
  final String apiBase;

  /// La valeur de l'en-tête Authorization de ton API pour l'utilisateur connecté,
  /// ex. () async => 'Bearer $jwt'. Rend null si personne n'est connecté.
  final Future<String?> Function() enteteAuthorization;

  /// Appelé quand l'utilisateur touche une notification : navigue vers cette adresse.
  final void Function(String url) ouvrirUrl;

  /// Appelé quand un push arrive appli OUVERTE. Sur Android, le système n'affiche
  /// rien dans ce cas : montre un bandeau dans l'appli (SnackBar, ou flutter_local_notifications).
  final void Function(RemoteMessage message)? auPremierPlan;

  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  StreamSubscription<String>? _rafraichissement;
  bool _ecoutesBranchees = false;

  /// À appeler une fois l'utilisateur connecté.
  Future<void> activer() async {
    // Affiche la demande système sur iPhone et sur Android 13 ou plus.
    final reglages = await _messaging.requestPermission(alert: true, badge: true, sound: true);
    if (reglages.authorizationStatus == AuthorizationStatus.denied) {
      debugPrint('Push : notifications refusées par l\'utilisateur');
      return;
    }

    // iPhone : afficher aussi les notifications quand l'appli est ouverte.
    await _messaging.setForegroundNotificationPresentationOptions(alert: true, badge: true, sound: true);

    // iPhone : Firebase ne donne son jeton qu'une fois le jeton Apple arrivé.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.iOS) {
      String? jetonApple = await _messaging.getAPNSToken();
      for (var essai = 0; jetonApple == null && essai < 10; essai++) {
        await Future<void>.delayed(const Duration(seconds: 1));
        jetonApple = await _messaging.getAPNSToken();
      }
      if (jetonApple == null) {
        debugPrint('Push : pas de jeton Apple. Vrai iPhone ? Capacité « Push Notifications » cochée dans Xcode ?');
        return;
      }
    }

    final jeton = await _messaging.getToken();
    if (jeton != null) await _enregistrer(jeton);
    // Firebase change parfois le jeton : le serveur doit toujours avoir le dernier.
    _rafraichissement ??= _messaging.onTokenRefresh.listen(_enregistrer);

    if (!_ecoutesBranchees) {
      _ecoutesBranchees = true;
      FirebaseMessaging.onMessageOpenedApp.listen(_ouvrir); // appli en arrière-plan
      FirebaseMessaging.onMessage.listen((message) => auPremierPlan?.call(message));
    }
    final initial = await _messaging.getInitialMessage(); // appli fermée, ouverte par la notification
    if (initial != null) _ouvrir(initial);
  }

  /// À appeler à la déconnexion, AVANT d'oublier le jeton de connexion à l'API.
  Future<void> desactiver() async {
    final jeton = await _messaging.getToken();
    if (jeton != null) await _requete('DELETE', {'token': jeton});
    await _rafraichissement?.cancel();
    _rafraichissement = null;
    await _messaging.deleteToken();
  }

  void _ouvrir(RemoteMessage message) {
    final url = message.data['url'];
    if (url is String && url.isNotEmpty) ouvrirUrl(url);
  }

  Future<void> _enregistrer(String jeton) => _requete('POST', {'kind': 'fcm', 'token': jeton});

  Future<void> _requete(String methode, Map<String, Object> corps) async {
    final authorization = await enteteAuthorization();
    if (authorization == null) return;
    final client = http.Client();
    try {
      final requete = http.Request(methode, Uri.parse('$apiBase/appareils/'))
        ..headers.addAll({'Content-Type': 'application/json', 'Authorization': authorization})
        ..body = jsonEncode(corps);
      final reponse = await http.Response.fromStream(await client.send(requete));
      final dejaRetire = methode == 'DELETE' && reponse.statusCode == 404;
      if (reponse.statusCode >= 400 && !dejaRetire) {
        debugPrint('Push : le serveur a refusé ($methode, HTTP ${reponse.statusCode}) ${reponse.body}');
      }
    } catch (erreur) {
      debugPrint('Push : serveur injoignable ($erreur)');
    } finally {
      client.close();
    }
  }
}
