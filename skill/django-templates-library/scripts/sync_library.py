#!/usr/bin/env python3
"""Trouve la librairie django-templates, verifie qu'elle est a jour, et la met a jour si besoin.

    python sync_library.py [--dir CHEMIN]

Ou chercher le clone, dans l'ordre : --dir, la variable DJANGO_TEMPLATES_DIR,
~/django-templates, ~/Desktop/django-templates. Sans clone : clonage dans
--dir, DJANGO_TEMPLATES_DIR ou ~/django-templates.

La derniere ligne de sortie est un JSON :
    {"status": ..., "path": ..., "ref": ..., "detail": ...}

    status a_jour               le clone est sur main et a jour : rien a faire
           mis_a_jour           il etait en retard, sans travail local : il vient d'etre mis a jour
           clone                il n'existait pas : il vient d'etre clone
           lecture_origin_main  du travail local non fusionne : rien n'est touche,
                                la version a jour se lit dans origin/main (git show / git archive)
           hors_ligne           GitHub injoignable : version locale, fraicheur NON verifiee
           erreur               dossier qui n'est pas la librairie, ou clonage impossible
    ref    ce qu'il faut lire : "HEAD" (les fichiers du dossier) ou "origin/main"

Le script ne detruit jamais rien : ni modification locale, ni commit non pousse.
Seule dependance : git. Python 3.8+, bibliotheque standard uniquement.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_URL = os.environ.get("DJANGO_TEMPLATES_REPO_URL", "https://github.com/TokDar2410621/django-templates.git")
REPO_SLUG = "tokdar2410621/django-templates"
BRANCH = "main"
TIMEOUT = 120


def git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=TIMEOUT
    )


def candidates(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    liste = []
    env = os.environ.get("DJANGO_TEMPLATES_DIR", "").strip()
    if env:
        liste.append(Path(env).expanduser())
    home = Path.home()
    liste += [home / "django-templates", home / "Desktop" / "django-templates"]
    return liste


def is_library(path: Path) -> bool:
    if not (path / ".git").exists():
        return False
    origine = git(path, "remote", "get-url", "origin").stdout.strip().lower().replace("\\", "/")
    return REPO_SLUG in origine


def result(status: str, path: Path | None, ref: str, detail: str) -> dict:
    return {"status": status, "path": str(path) if path else "", "ref": ref, "detail": detail}


def sync(explicit: str | None = None) -> dict:
    found = next((p for p in candidates(explicit) if is_library(p)), None)

    if found is None:
        cible = Path(explicit or os.environ.get("DJANGO_TEMPLATES_DIR", "").strip() or Path.home() / "django-templates").expanduser()
        if cible.exists() and any(cible.iterdir()):
            return result("erreur", cible, "", "ce dossier existe mais n'est pas un clone de la librairie : donne le bon chemin (--dir)")
        clonage = subprocess.run(
            ["git", "clone", "--quiet", "--branch", BRANCH, REPO_URL, str(cible)],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if clonage.returncode != 0:
            return result("erreur", cible, "", f"clonage impossible : {clonage.stderr.strip()[:200]}")
        return result("clone", cible, "HEAD", f"clone neuf de {BRANCH}")

    if git(found, "fetch", "--quiet", "origin", BRANCH).returncode != 0:
        return result("hors_ligne", found, "HEAD", "GitHub injoignable : version locale utilisee, fraicheur NON verifiee")

    branche = git(found, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    modifie = bool(git(found, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    retard = int(git(found, "rev-list", "--count", f"HEAD..origin/{BRANCH}").stdout.strip() or 0)
    avance = int(git(found, "rev-list", "--count", f"origin/{BRANCH}..HEAD").stdout.strip() or 0)

    if branche == BRANCH:
        if retard == 0:
            note = f" ({avance} commit(s) local(aux) non pousse(s))" if avance else ""
            return result("a_jour", found, "HEAD", f"main est a jour{note}")
        if not modifie and avance == 0:
            if git(found, "merge", "--quiet", "--ff-only", f"origin/{BRANCH}").returncode == 0:
                return result("mis_a_jour", found, "HEAD", f"{retard} commit(s) recupere(s) sur main")
        raison = "fichiers modifies localement" if modifie else "main local a diverge d'origin/main"
        return result("lecture_origin_main", found, f"origin/{BRANCH}", f"{raison} : rien n'a ete touche")

    # Une autre branche. Deja fusionnee et sans modification : on repasse sur main sans rien perdre.
    fusionnee = git(found, "merge-base", "--is-ancestor", "HEAD", f"origin/{BRANCH}").returncode == 0
    if fusionnee and not modifie:
        if git(found, "checkout", "--quiet", BRANCH).returncode == 0:
            if git(found, "merge", "--quiet", "--ff-only", f"origin/{BRANCH}").returncode == 0:
                return result("mis_a_jour", found, "HEAD", f"branche {branche} deja fusionnee : repasse sur main, a jour")
            return result("lecture_origin_main", found, f"origin/{BRANCH}", "main local a diverge d'origin/main : rien n'a ete fusionne")
    raison = "fichiers modifies localement" if modifie else "commits non fusionnes dans main"
    return result("lecture_origin_main", found, f"origin/{BRANCH}", f"branche {branche}, {raison} : rien n'a ete touche")


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronise la librairie django-templates.")
    parser.add_argument("--dir", help="chemin du clone (sinon DJANGO_TEMPLATES_DIR, ~/django-templates, ~/Desktop/django-templates)")
    args = parser.parse_args()
    try:
        etat = sync(args.dir)
    except FileNotFoundError:
        etat = result("erreur", None, "", "git n'est pas installe")
    except subprocess.TimeoutExpired:
        etat = result("hors_ligne", None, "HEAD", "git trop lent (delai depasse) : fraicheur NON verifiee")
    print(f"[django-templates] {etat['status']} : {etat['detail']} ({etat['path']})")
    print(json.dumps(etat, ensure_ascii=False))
    return 1 if etat["status"] == "erreur" else 0


if __name__ == "__main__":
    sys.exit(main())
