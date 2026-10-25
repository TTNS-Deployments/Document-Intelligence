import pytest

from docintel import results, settings_store
from docintel.config import get_settings, reset_settings_cache
from docintel.factory import get_blob_store
from docintel.storage import PreconditionFailed
from sdk_fixtures import record


def test_local_store_etags_and_conditions():
    store = get_blob_store()
    etag = store.put_bytes("c", "a.json", b"1", if_none_match=True)
    with pytest.raises(PreconditionFailed):
        store.put_bytes("c", "a.json", b"2", if_none_match=True)
    with pytest.raises(PreconditionFailed):
        store.put_bytes("c", "a.json", b"2", if_match="stale")
    new = store.put_bytes("c", "a.json", b"2", if_match=etag)
    assert new != etag and store.get_with_etag("c", "a.json") == (b"2", new)
    store.put_bytes("c", "dir/b.bin", b"xyz", metadata={"k": "v"})
    infos = store.list_info("c")
    assert [i.name for i in infos] == ["a.json", "dir/b.bin"]
    assert infos[1].metadata == {"k": "v"} and infos[1].size == 3
    assert b"".join(store.iter_chunks("c", "dir/b.bin", 2)) == b"xyz"
    assert store.delete("c", "a.json") and not store.delete("c", "a.json")
    for bad in ("../x", ".meta/x", "a/../../b"):
        with pytest.raises(ValueError):
            store.put_bytes("c", bad, b"")


def test_history_rows_come_from_metadata():
    rec = record(filename="Rechnung März 2026.pdf", status="done", owner="s9")
    rec["analysis"]["documents"][0]["fields"]["InvoiceId"]["confidence"] = 0.5
    results.create(rec, b"%PDF-1.4")
    row = results.list_summaries()[0]
    assert row["filename"] == "Rechnung März 2026.pdf"  # percent-encoded in metadata, decoded here
    assert row["status"] == "done" and row["owner"] == "s9" and row["review_count"] == 2
    assert row["model_id"] == "prebuilt-invoice" and row["pages"] == 2


def test_delete_removes_result_and_original():
    rec = record()
    results.create(rec, b"%PDF-1.4 data")
    s = get_settings()
    assert get_blob_store().list(s.container_uploads) == [f"{rec['id']}/invoice.pdf"]
    assert results.delete(rec["id"])
    assert get_blob_store().list(s.container_uploads) == []
    with pytest.raises(results.NotFound):
        results.get(rec["id"])


def test_invalid_ids_are_not_found():
    for bad in ("../secret", "ABCDEF", "", "0123456789abcdeg"):
        with pytest.raises(results.NotFound):
            results.get(bad)


def test_update_retries_on_concurrent_change():
    rec = record()
    results.create(rec, b"%PDF")
    requests_made = []

    def change(r):
        requests_made.append(1)
        if len(requests_made) == 1:  # someone else writes between our read and write
            other, etag = results.get_with_etag(rec["id"])
            other["edits"] = {"InvoiceId": {"value": "X", "at": "t", "by": "Admin"}}
            results.save(other, etag)
        r["reviewed"] = ["VendorName"]

    updated = results.update(rec["id"], change)
    assert len(requests_made) == 2 and updated["edits"]["InvoiceId"]["value"] == "X" and updated["reviewed"] == ["VendorName"]


def test_runtime_settings_precedence(monkeypatch):
    assert settings_store.get_runtime_settings()["review_threshold"] == 0.80  # Config/settings.yaml
    monkeypatch.setenv("REVIEW_THRESHOLD", "0.7")
    monkeypatch.setenv("RETENTION_DAYS", "30")
    reset_settings_cache()
    values = settings_store.get_runtime_settings()
    assert values["review_threshold"] == 0.7 and values["retention_days"] == 30  # env
    values = settings_store.save_runtime_settings({"review_threshold": "0.9", "daily_page_limit": 50})
    assert values["review_threshold"] == 0.9 and values["daily_page_limit"] == 50  # saved by an Admin wins
    for bad in ({"review_threshold": 2}, {"max_pages": 0}, {"retention_days": 1}, {"daily_page_limit": "lots"}):
        with pytest.raises(settings_store.SettingsError):
            settings_store.save_runtime_settings(bad)


def test_keyvault_reference_is_treated_as_empty(monkeypatch):
    monkeypatch.setenv("DOCINTEL_ENDPOINT", "@Microsoft.KeyVault(VaultName=kv;SecretName=x)")
    reset_settings_cache()
    assert get_settings().docintel_endpoint == ""


def test_azure_mode_defaults(monkeypatch):
    monkeypatch.setenv("DOCINTEL_MODE", "azure")
    reset_settings_cache()
    s = get_settings()
    assert (s.storage_backend, s.analyze_backend) == ("azure", "azure")
    monkeypatch.setenv("DOCINTEL_MODE", "cloud")
    reset_settings_cache()
    with pytest.raises(ValueError):
        get_settings()
