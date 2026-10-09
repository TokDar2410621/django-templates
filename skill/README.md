# Le skill Claude Code de la librairie

`django-templates-library/` est un skill Claude Code : avant tout travail de
backend Django, Claude synchronise cette librairie (clone si absente, mise a
jour si en retard), lit `CATALOG.md` et applique le bon mode
(REUSE / ITERATE / EXTRACT / CREATE).

## Installer

Copie le dossier `django-templates-library/` dans `~/.claude/skills/` :

```bash
git clone https://github.com/TokDar2410621/django-templates ~/django-templates
cp -r ~/django-templates/skill/django-templates-library ~/.claude/skills/
```

Sous Windows (PowerShell) :

```powershell
git clone https://github.com/TokDar2410621/django-templates "$HOME\django-templates"
Copy-Item -Recurse "$HOME\django-templates\skill\django-templates-library" "$HOME\.claude\skills\"
```

Le clone n'est pas obligatoire : au premier usage, le skill clone la
librairie lui-meme dans `~/django-templates`. Pour la ranger ailleurs, pose
la variable `DJANGO_TEMPLATES_DIR`.

## Ce que fait la verification de fraicheur

`django-templates-library/scripts/sync_library.py`, lance par le skill avant
chaque usage :

- clone a jour : il continue ;
- clone en retard, sans travail local : il le met a jour, puis continue ;
- clone reste sur une branche deja fusionnee : il repasse sur main, a jour ;
- travail local non fusionne ou fichiers modifies : il ne touche a rien et lit
  la version a jour dans `origin/main` ;
- GitHub injoignable : il continue en local et le signale.

Il ne detruit jamais un travail local. Tests : `pytest skill/tests` (11 cas,
contre de vrais depots git).
