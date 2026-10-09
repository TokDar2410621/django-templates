# Django Templates Library : mode d'emploi pour tout agent

Librairie personnelle de Darius : des apps Django completes, testees, pretes a
copier dans un projet. Ce fichier est charge automatiquement par Claude Code
sur toute machine qui clone ce repo : c'est le skill embarque.

## Avant TOUTE feature backend Django, dans cet ordre

1. Lis `CATALOG.md` : l'index complet et autoritaire des templates.
2. Lis `README.md` : l'usage de la librairie.
3. Si un template correspond au besoin : lis `apps/<slug>/README.md` + `SETTINGS.md`.

Ajouts recents : `realtime_messaging` (chat temps reel Redis + Channels,
extrait de SMN et FIN) et `voice_messages` (notes vocales autonomes) ;
integration declaree entre les deux, jamais d'import croise.
`push_notifications` (2026-10-09) : push navigateur, Android et iPhone (Web Push,
Firebase v1, APNs, Expo) et client Flutter ; `notifications_multichannel` garde
courriel, SMS et Web Push.

## Le skill Claude Code

Le skill de cette librairie vit dans `skill/django-templates-library/` (installation :
`skill/README.md`). Avant chaque usage, il lance `scripts/sync_library.py` : clone si
absente, mise a jour si en retard, et jamais rien d'ecrase s'il y a du travail local.
Toute evolution du skill se fait ICI, puis se recopie dans `~/.claude/skills/`.

## Les quatre modes (declare le mode en premiere ligne de ta reponse)

- **REUSE** : un template couvre le besoin. Copie `apps/<slug>/` dans le projet,
  suis son `SETTINGS.md`, cable URLs + INSTALLED_APPS, migre. N'invente rien.
- **ITERATE** : le template existe mais un projet source l'a ameliore. Produis la
  v1.1 ici (SemVer + changelog).
- **EXTRACT** : pas de template, mais un projet de reference a du code qui marche.
  Presente Option A (extraire-abstraire) vs Option B (reecrire) et ATTENDS.
- **CREATE** : personne ne l'a. Deux questions max (quels projets l'utiliseront ?
  quelle complexite ?), puis conception avec biais reutilisable.

## REUSE : renommer a la copie (CRITIQUE)

Les noms de modules sont generiques expres. Avant de copier, demande le nom de
module voulu par le projet (defaut = nom de la lib). Si different : renomme le
dossier, `apps.py` (name + label), tous les imports internes, `app_name` dans
`urls.py`, les `db_table`, et les exemples des README/SETTINGS. Une passe
find-replace Python sur les `.py` et `.md` du dossier copie suffit.

## Criteres production (non negociables pour tout travail de template)

Type hints publics ; tests pytest qui passent (happy path + 2 negatifs mini) ;
migration initiale unique ; admin par modele (avec fallback ImportError pour
django-unfold) ; erreurs explicites, jamais `except: pass` ; logging via
`logging.getLogger(__name__)` ; docstrings publics ; decoupage
services/selectors/views ; settings via `getattr(settings, ...)` ; JAMAIS
`from django.contrib.auth.models import User` (toujours `AUTH_USER_MODEL` /
`get_user_model()`) ; validation au bon niveau ; snake_case pour les modules.

## Ou vit la verite

Ce repo EST la source de verite. Toute amelioration de template se commite ICI
(branche + PR si le changement est structurel), jamais en copie divergente dans
un projet consommateur. Si tu n'es pas Darius : le repo est public en lecture ;
propose tes ameliorations en PR, ne pousse pas sur main.

Machines de Darius seulement : le clone canonique de PC1 vit a
`C:/Users/Darius/Desktop/django-templates` ; ailleurs, resous le repo via la
carte des repos du cerveau (`04-systemes/repos.md`).

Vitrine en ligne (les 13 apps montees, actives ou dormantes selon les cles) :
https://web-production-7b1cc.up.railway.app

## Interdits

Aucun em-dash dans la prose. Aucun secret reel dans les templates : les
SETTINGS.md ne montrent que des placeholders. Une app de la lib n'importe
jamais une autre app de la lib sans le declarer dans son SETTINGS.md.
