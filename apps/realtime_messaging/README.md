═════════════════════════════════════════════
Template : realtime-messaging
Version  : 1.0.1
Mode     : EXTRACT-A
Source   : FIN/apps/conversations (coeur) + SMN/apps/conversations (types media, durees)
Stack    : Django 5+ / DRF / Channels / Redis
Deps     : channels, redis, djangorestframework, djangorestframework-simplejwt
Used by  : (vide)
═════════════════════════════════════════════

# Realtime Messaging (Redis + Channels)

## Changelog

### 1.0.1 (2026-10-09)

`JWTAuthMiddleware` ne remplace plus `scope["user"]` par `AnonymousUser`
quand `?token=` manque. Empile sous `AuthMiddlewareStack` (session et JWT sur
le meme WebSocket), il deconnectait en silence tout client authentifie par
cookie. Meme correction dans `snippets/channels_jwt_middleware.py`. Test :
`tests/test_middleware.py`, qui echoue sur la 1.0.0.

Messagerie temps reel entre utilisateurs, extraite de deux systemes en
production : SendMeNow (messagerie au coeur du produit) et FindItNow (chat
trouveur-proprietaire). L'architecture familiale est conservee :

- **Messages ephemeres dans Redis** avec TTL par message (defaut 7 jours,
  configurable). C'est un choix produit assume : une conversation vivante,
  pas une archive. La persistance Postgres (modele SMN Sprint 4) est le
  candidat naturel de la v1.1.
- **Postgres pour le durable** : les blocages entre utilisateurs.
- **Channels pour le direct** : le WebSocket est une firehose en lecture
  seule par conversation ; toutes les ECRITURES passent par DRF (validation,
  blocages, rate-limit concentres au meme endroit).

## Ce que le template offre

- Conversations a 2+ participants, idempotentes par `ref` externe optionnel
  (`item:42:finder:7`, `commande:9`...) : re-contacter le meme contexte
  rouvre la meme conversation.
- Messages `text`, `photo`, `video`, `audio` (le contenu des types media est
  une URL ; voir le template `voice_messages` pour produire celle de l'audio,
  avec `duration` portee par le message).
- Reponses citees (extrait + expediteur + type), reactions emoji (toggle),
  suppression par l'expediteur, marquage lu, inbox agregee (derniere +
  non-lus) en un appel.
- Blocages directionnels avec verrou des deux sens (`Block.between`).
- Mode dormant : sans Redis configure, les endpoints repondent 503 avec un
  message explicite, jamais 500.

## Endpoints

    POST   conversations/                      {participant_ids, ref?}
    GET    conversations/                      inbox (derniere + non-lus)
    GET    conversations/<id>/messages/
    POST   conversations/<id>/messages/        {content, msg_type?, duration?, reply_to_id?}
    POST   conversations/<id>/read/
    DELETE messages/<id>/
    POST   messages/<id>/reaction/             {emoji}
    POST   blocks/  |  DELETE blocks/          {user_id}

WebSocket : `ws://hote/ws/messaging/<conv_id>/?token=<jwt>` : envoie
`{"kind": "history"}` a la connexion puis relaie `message`, `read`,
`deleted`, `reaction`.

## Ce qui est reste dans les projets sources (a dessein)

- SMN : la persistance Postgres des conversations (upgrade Redis -> durable),
  les sondages (`poll`), la machinerie 4 etats de livraison.
- FIN : `ContactHistory` (ancre sur un Item projet-specifique).
