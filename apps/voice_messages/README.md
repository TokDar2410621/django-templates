═════════════════════════════════════════════
Template : voice-messages
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : SMN/apps/conversations (upload media + duration + types audio)
Stack    : Django 5+ / DRF
Deps     : djangorestframework
Used by  : (vide)
═════════════════════════════════════════════

# Voice Messages

Notes vocales en app autonome, extraites de SendMeNow ou l'audio etait tisse
dans le chat (msg_type="audio", contenu = URL S3, duree sur le message).
Separees a dessein : stocker et valider une note vocale est UNE
responsabilite ; quel message la transporte en est une autre.

## Ce que le template offre

- Modele `VoiceMessage` : fichier (via `default_storage`, donc S3 automatique
  avec le snippet `storage_s3_autoswitch.py`), type MIME, taille, duree,
  expediteur, `ref` libre vers ton systeme de messagerie (`rtm:<conv_id>`...).
- Validation reglable par settings : types permis (webm/ogg/m4a/mp3/wav par
  defaut, soit MediaRecorder web + iOS + Android), taille max (10 Mo), duree
  max (300 s). La duree vient du client (MediaRecorder la connait) et est
  BORNEE ici ; la sonde serveur (ffprobe) est un durcissement par projet,
  documente dans SETTINGS.md.
- Upload multipart authentifie, lecture de metadonnees, suppression par
  l'expediteur seulement (fichier + rangee).

## Endpoints

    POST   upload/            multipart {file, duration_seconds, ref?} -> {id, url, duration_seconds, ...}
    GET    <uuid>/            metadonnees
    DELETE <uuid>/            expediteur seulement (supprime aussi le fichier)

## Integration declaree (jamais d'import croise)

Avec `realtime_messaging` (ou tout autre chat) : uploader ici, puis poster un
message `{"msg_type": "audio", "content": "<url>", "duration": <s>}` dans la
conversation. Le lecteur cote client n'a besoin que de l'URL et de la duree.
