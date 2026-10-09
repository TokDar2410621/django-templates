"""sync_library.py contre de vrais depots git : un "GitHub" local (depot nu) et des clones.

    pytest skill/tests
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "django-templates-library" / "scripts" / "sync_library.py"


def run(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Un "GitHub" local dont le chemin contient le slug du depot, et un HOME isole."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("DJANGO_TEMPLATES_DIR", raising=False)

    distant = tmp_path / "TokDar2410621" / "django-templates.git"
    distant.parent.mkdir()
    run("init", "--quiet", "--bare", "--initial-branch=main", str(distant))
    auteur = tmp_path / "auteur"
    run("clone", "--quiet", str(distant), str(auteur))
    (auteur / "CATALOG.md").write_text("| `a` | 1.0.0 |\n", encoding="utf-8")
    run("add", "CATALOG.md", cwd=auteur)
    run("commit", "--quiet", "-m", "catalogue v1", cwd=auteur)
    run("push", "--quiet", "origin", "main", cwd=auteur)
    monkeypatch.setenv("DJANGO_TEMPLATES_REPO_URL", str(distant))
    return {"tmp": tmp_path, "home": home, "distant": distant, "auteur": auteur}


def publier(env, contenu: str) -> str:
    """Un nouveau commit sur le main du "GitHub" (comme un merge de PR)."""
    (env["auteur"] / "CATALOG.md").write_text(contenu, encoding="utf-8")
    run("commit", "--quiet", "-am", "nouvelle version", cwd=env["auteur"])
    run("push", "--quiet", "origin", "main", cwd=env["auteur"])
    return run("rev-parse", "HEAD", cwd=env["auteur"])


def cloner(env, ou: Path) -> Path:
    run("clone", "--quiet", str(env["distant"]), str(ou))
    return ou


def sync(dossier: Path | None = None) -> dict:
    args = [sys.executable, str(SCRIPT)] + (["--dir", str(dossier)] if dossier else [])
    sortie = subprocess.run(args, capture_output=True, text=True)
    return json.loads(sortie.stdout.strip().splitlines()[-1])


def test_a_jour_ne_touche_a_rien(env):
    clone = cloner(env, env["home"] / "django-templates")
    avant = run("rev-parse", "HEAD", cwd=clone)
    etat = sync()
    assert etat["status"] == "a_jour"
    assert Path(etat["path"]) == clone
    assert run("rev-parse", "HEAD", cwd=clone) == avant


def test_en_retard_est_mis_a_jour(env):
    clone = cloner(env, env["home"] / "django-templates")
    nouveau = publier(env, "| `a` | 1.0.0 |\n| `b` | 1.0.0 |\n")
    etat = sync()
    assert etat["status"] == "mis_a_jour"
    assert run("rev-parse", "HEAD", cwd=clone) == nouveau
    assert "`b`" in (clone / "CATALOG.md").read_text(encoding="utf-8")


def test_clone_sur_le_bureau_trouve_et_mis_a_jour(env):
    """Le cas de Darius : le clone vit dans ~/Desktop/django-templates."""
    clone = cloner(env, env["home"] / "Desktop" / "django-templates")
    nouveau = publier(env, "v2\n")
    etat = sync()
    assert etat["status"] == "mis_a_jour"
    assert run("rev-parse", "HEAD", cwd=clone) == nouveau


def test_ancienne_branche_deja_fusionnee_repasse_sur_main(env):
    """Le cas vecu le 2026-10-09 : clone reste sur une branche deja fusionnee."""
    clone = cloner(env, env["home"] / "django-templates")
    run("checkout", "--quiet", "-b", "fix/ancienne", cwd=clone)
    nouveau = publier(env, "v2\n")
    etat = sync()
    assert etat["status"] == "mis_a_jour"
    assert run("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "main"
    assert run("rev-parse", "HEAD", cwd=clone) == nouveau


def test_modifications_locales_jamais_ecrasees(env):
    clone = cloner(env, env["home"] / "django-templates")
    (clone / "CATALOG.md").write_text("mon travail en cours\n", encoding="utf-8")
    publier(env, "v2\n")
    etat = sync()
    assert etat["status"] == "lecture_origin_main"
    assert etat["ref"] == "origin/main"
    assert (clone / "CATALOG.md").read_text(encoding="utf-8") == "mon travail en cours\n"
    # La version a jour reste lisible sans toucher au dossier.
    assert run("show", "origin/main:CATALOG.md", cwd=clone) == "v2"


def test_branche_avec_travail_non_fusionne_jamais_touchee(env):
    clone = cloner(env, env["home"] / "django-templates")
    run("checkout", "--quiet", "-b", "feat/en-cours", cwd=clone)
    (clone / "NOUVEAU.md").write_text("brouillon\n", encoding="utf-8")
    run("add", "NOUVEAU.md", cwd=clone)
    run("commit", "--quiet", "-m", "travail non fusionne", cwd=clone)
    publier(env, "v2\n")
    etat = sync()
    assert etat["status"] == "lecture_origin_main"
    assert run("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "feat/en-cours"
    assert (clone / "NOUVEAU.md").exists()


def test_fichiers_non_suivis_ne_bloquent_pas_la_mise_a_jour(env):
    """Des artefacts locaux (venv, uploads de tests) ne doivent pas empecher la mise a jour."""
    clone = cloner(env, env["home"] / "django-templates")
    (clone / "artefact-local.txt").write_text("x\n", encoding="utf-8")
    nouveau = publier(env, "v2\n")
    assert sync()["status"] == "mis_a_jour"
    assert run("rev-parse", "HEAD", cwd=clone) == nouveau


def test_pas_de_clone_on_clone(env):
    etat = sync()
    assert etat["status"] == "clone"
    assert (env["home"] / "django-templates" / "CATALOG.md").exists()


def test_github_injoignable_continue_en_local(env):
    clone = cloner(env, env["home"] / "django-templates")
    env["distant"].rename(env["distant"].with_name("ailleurs.git"))
    etat = sync()
    assert etat["status"] == "hors_ligne"
    assert "NON verifiee" in etat["detail"]
    assert Path(etat["path"]) == clone


def test_dossier_qui_n_est_pas_la_librairie(env):
    autre = env["tmp"] / "autre-chose"
    autre.mkdir()
    (autre / "fichier.txt").write_text("x\n", encoding="utf-8")
    etat = sync(autre)
    assert etat["status"] == "erreur"


def test_variable_d_environnement_prioritaire(env, monkeypatch):
    ailleurs = cloner(env, env["tmp"] / "mes-libs" / "dt")
    cloner(env, env["home"] / "django-templates")
    monkeypatch.setenv("DJANGO_TEMPLATES_DIR", str(ailleurs))
    assert Path(sync()["path"]) == ailleurs
