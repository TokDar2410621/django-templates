---
name: django-templates-library
description: Use BEFORE building any Django / DRF backend feature (auth, billing, email, push notifications, realtime chat, voice messages, RAG, AI generation, moderation, QR tags, teams, newsletters, shop, Stripe Connect...). Triggers - Django/DRF backend task, "Django app", "Django model", "DRF view/serializer", "manage.py", "INSTALLED_APPS", "REUSE template". First syncs the public library github.com/TokDar2410621/django-templates (clones it if missing, updates it if behind), then reads its CATALOG.md and applies the REUSE / ITERATE / EXTRACT / CREATE workflow. SKIP for frontend-only tasks and non-Django backends.
---

# Librairie django-templates

Des apps Django completes, testees, pretes a copier dans un projet :
https://github.com/TokDar2410621/django-templates (public, licence MIT).
Ce skill marche sur n'importe quelle machine : il trouve ou clone la
librairie, et verifie qu'elle est a jour avant chaque usage.

## Etape 0 : une librairie a jour, a chaque fois

Avant de lire quoi que ce soit dans la librairie, lance le script livre avec
ce skill (`<dossier du skill>` = le « Base directory » affiche au chargement) :

```bash
python "<dossier du skill>/scripts/sync_library.py"
```

Il cherche le clone dans `$DJANGO_TEMPLATES_DIR`, puis `~/django-templates`,
puis `~/Desktop/django-templates`, interroge GitHub et agit selon le cas.
La derniere ligne de sa sortie est un JSON : `status`, `path` (le clone),
`ref` (ce qu'il faut lire), `detail`.

| `status` | Situation | Ce que le script a fait | Ce que tu fais |
|---|---|---|---|
| `a_jour` | clone sur main, rien de nouveau | rien | continue le travail |
| `mis_a_jour` | clone en retard, sans travail local (y compris resté sur une branche deja fusionnee) | mise a jour, retour sur main | continue le travail |
| `clone` | aucun clone | clone dans `~/django-templates` (ou `$DJANGO_TEMPLATES_DIR`) | continue le travail |
| `lecture_origin_main` | travail local non fusionne ou fichiers modifies | rien : il ne detruit jamais un travail | lis la version a jour dans `origin/main` (voir plus bas) et dis-le a l'utilisateur |
| `hors_ligne` | GitHub injoignable | rien | continue avec le clone local et dis « fraicheur non verifiee » |
| `erreur` | dossier qui n'est pas la librairie, ou clonage impossible | rien | dis-le et demande le bon chemin (`--dir`) |

Lire dans `origin/main` sans toucher au clone :

```bash
git -C "<path>" show origin/main:CATALOG.md
git -C "<path>" archive origin/main apps/<slug> | tar -x -C <dossier du projet>   # copier un template
```

Sans terminal (claude.ai) : lis les fichiers bruts, toujours a jour, par exemple
https://raw.githubusercontent.com/TokDar2410621/django-templates/main/CATALOG.md
puis `.../main/apps/<slug>/README.md` et `.../main/apps/<slug>/SETTINGS.md`.

Sans Python : les memes etapes a la main, `git -C <clone> fetch origin main`,
puis `git -C <clone> status -sb`, et `git -C <clone> merge --ff-only origin/main`
seulement si le clone est sur main, sans modification locale.

## Etape 1 : lire avant de construire

1. `CATALOG.md` : la liste a jour des templates. Jamais une liste de memoire :
   la librairie grandit.
2. `README.md` a la racine : l'usage de la librairie.
3. Le template qui correspond : `apps/<slug>/README.md` (ce qu'il fait, son
   API, ce qu'il ne fait pas) et `apps/<slug>/SETTINGS.md` (installation).

Le `CLAUDE.md` du depot detaille les memes regles.

## Etape 2 : declarer le mode, en premiere ligne de ta reponse

- **REUSE** : un template couvre le besoin. Copie-le, suis son `SETTINGS.md`,
  n'invente rien.
- **ITERATE** : le template existe, mais le projet en a une version amelioree.
  L'amelioration va dans la librairie (branche + PR), jamais en copie
  divergente dans le projet.
- **EXTRACT** : pas de template, mais un projet a du code qui marche. Presente
  l'option A (extraire et abstraire le code existant) et l'option B (reecrire),
  puis ATTENDS le choix.
- **CREATE** : personne ne l'a. Deux questions au plus (quels projets
  l'utiliseront ? quelle complexite ?), puis conception reutilisable.

## REUSE : copier et renommer

1. Demande le nom de module voulu par le projet (defaut : le nom de la librairie).
2. Copie `<path>/apps/<slug>/` dans le dossier d'apps du projet (ou
   `git archive` si `ref` vaut `origin/main`).
3. Si le nom change, renomme partout : le dossier, `apps.py` (`name`, `label`),
   les imports internes, `app_name` dans `urls.py`, les `db_table`, les exemples
   des README et SETTINGS. Une passe suffit :

   ```bash
   python -c "import pathlib; root = pathlib.Path('apps/<nouveau>'); old, new = '<slug>', '<nouveau>'; [p.write_text(p.read_text(encoding='utf-8').replace(old, new), encoding='utf-8') for p in root.rglob('*') if p.is_file() and p.suffix in ('.py', '.md')]"
   ```

4. Suis `SETTINGS.md` : dependances pip, `INSTALLED_APPS`, URLs, variables
   d'environnement, `python manage.py migrate`.
5. Lance les tests du template : `pytest apps/<nouveau>/tests/`.

## Criteres production (tout travail de template)

Type hints publics ; tests pytest qui passent (cas normal + 2 cas d'erreur au
moins) ; une seule migration initiale ; un admin par modele (avec repli si
django-unfold manque) ; erreurs explicites, jamais `except: pass` ; logs via
`logging.getLogger(__name__)` ; docstrings publics ; decoupage
`services.py` / `selectors.py` / `views.py` ; reglages via
`getattr(settings, ...)` avec des defauts sains ; JAMAIS
`from django.contrib.auth.models import User` (toujours `settings.AUTH_USER_MODEL`
ou `get_user_model()`) ; validation au bon niveau (serializer = forme,
service = regles) ; modules en snake_case.

## Contribuer

Le depot est la source de verite. Tu n'es pas son proprietaire : propose tes
ameliorations en PR sur GitHub, ne pousse jamais sur main.

## Interdits

Aucun secret reel dans un template (les SETTINGS.md ne montrent que des
exemples). Une app de la librairie n'importe jamais une autre app de la
librairie sans le declarer dans son SETTINGS.md.
