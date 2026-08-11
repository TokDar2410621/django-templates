"""Migration state tests : le modele et 0001_initial ne doivent jamais diverger.

Ce fichier existe a cause d'un bug vecu le 2026-08-10 en production sur
smart-post-assistant. Chaque demarrage affichait :

    Your models in app(s): 'rag_memory_pgvector' have changes that are not yet
    reflected in a migration, and so won't be applied.

Deux causes cumulees, toutes deux invisibles a la lecture :

1. Les index de Meta n'avaient pas de nom. Django en calcule alors un hache
   (rag_memory_tenant__491d5d_idx) qui ne peut jamais correspondre au nom
   explicite ecrit dans la migration.
2. Les dix help_text du modele, plus les choices de `kind`, n'existaient pas
   dans 0001_initial ecrite a la main.

Aucune des deux ne touche le schema en base, donc rien ne cassait. Le message
restait juste affiche a chaque boot, jusqu'a devenir du bruit qu'on n'ecoute
plus. Le jour ou une vraie divergence apparait, personne ne la voit.

Le piege supplementaire : 0001_initial est conditionnelle et ne s'applique que
sur Postgres. Sous SQLite l'autodetector propose un CreateModel complet, qui
appliquerait un CREATE TABLE sur une table existante. Ce test ne vaut donc que
sous Postgres, d'ou le skip.
"""
from __future__ import annotations

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState

APP_LABEL = "rag_memory_pgvector"


requires_app = pytest.mark.skipif(
    not apps.is_installed(APP_LABEL),
    reason=f"{APP_LABEL} n'est monte que sous Postgres (pgvector).",
)
requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="0001_initial est conditionnelle : elle ne s'applique que sur Postgres.",
)


@requires_app
@requires_postgres
def test_no_pending_migration() -> None:
    """Le modele ne doit rien avoir que les migrations ignorent.

    On passe par l'autodetector plutot que par `makemigrations --check` :
    la commande interroge la base pour verifier la coherence de l'historique,
    ce qui exige un Postgres reel. L'autodetector compare deux etats en
    memoire et n'ouvre aucune connexion.

    Quand ce test echoue, ne genere PAS la migration depuis SQLite : lance la
    commande avec des settings Postgres, sinon tu obtiendras un CreateModel qui
    cassera le demarrage des projets ou la table existe deja.
    """
    loader = MigrationLoader(None, ignore_no_migrations=True)
    autodetector = MigrationAutodetector(
        loader.project_state(),
        ProjectState.from_apps(apps),
    )
    changes = autodetector.changes(graph=loader.graph, trim_to_apps={APP_LABEL})
    pending = [
        op.describe()
        for migration in changes.get(APP_LABEL, [])
        for op in migration.operations
    ]
    assert not pending, (
        "Le modele a derive de ses migrations : "
        + " | ".join(pending)
        + ". Regenere avec des settings Postgres, verifie que le diff ne touche "
        "aucun attribut de schema (max_length, null, db_index, unique, default, "
        "dimensions), puis commite la migration."
    )


@requires_app
def test_indexes_are_explicitly_named() -> None:
    """Un index sans nom reintroduit la derive, meme si tout le reste va bien.

    Django genere alors un nom hache a partir des champs, qui ne correspondra
    jamais au nom ecrit dans la migration.
    """
    Memory = apps.get_model(APP_LABEL, "Memory")
    unnamed = [
        list(idx.fields) for idx in Memory._meta.indexes if not idx.name
    ]
    assert not unnamed, (
        f"Ces index n'ont pas de nom explicite : {unnamed}. "
        "Ajoute name=... et aligne-le sur celui de 0001_initial."
    )
