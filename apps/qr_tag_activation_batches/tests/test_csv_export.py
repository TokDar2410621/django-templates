"""CSV export tests."""
from __future__ import annotations

import csv
import io

import pytest

from qr_tag_activation_batches.services import bulk_export_csv


@pytest.mark.django_db
def test_csv_export_contains_one_row_per_code(code_batch):
    raw = bulk_export_csv(code_batch.pk)
    assert isinstance(raw, bytes)
    text = raw.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    # Header + N rows
    assert rows[0] == ["qr_slug", "activation_code", "public_url", "activation_url"]
    assert len(rows) == 1 + code_batch.size


@pytest.mark.django_db
def test_csv_export_code_mode_includes_activation_url(code_batch):
    raw = bulk_export_csv(code_batch.pk, frontend_base="https://example.test")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    rows = list(reader)
    for r in rows:
        assert r["qr_slug"]
        assert r["activation_code"]
        assert r["public_url"].startswith("https://example.test/q/")
        assert "activate?slug=" in r["activation_url"]


@pytest.mark.django_db
def test_csv_export_photo_mode_omits_activation_url(photo_batch):
    raw = bulk_export_csv(photo_batch.pk, frontend_base="https://example.test")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    rows = list(reader)
    for r in rows:
        assert r["qr_slug"]
        assert r["activation_code"] == ""
        assert r["public_url"].startswith("https://example.test/q/")
        assert r["activation_url"] == ""
