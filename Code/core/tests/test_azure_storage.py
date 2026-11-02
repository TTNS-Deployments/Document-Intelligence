"""The Azure Blob Storage code path. The first test needs nothing; the others run against the Azurite emulator when
AZURITE_CONNECTION_STRING is set (CI does; locally see Documents/local-development.md) and are skipped otherwise."""

import os
import uuid
from types import SimpleNamespace

import pytest

from docintel.storage import AzureBlobStore, PreconditionFailed

AZURITE = os.environ.get("AZURITE_CONNECTION_STRING", "")
needs_azurite = pytest.mark.skipif(not AZURITE, reason="set AZURITE_CONNECTION_STRING to run against Azurite")


def test_listing_turns_empty_metadata_into_empty_strings():
    """A blob listing returns metadata saved as "" as None; History and Batches read it as text."""
    now = object()
    props = SimpleNamespace(name="a.json", size=1, etag="e", creation_time=now, last_modified=now,
                            metadata={"error": None, "status": "done"})
    assert AzureBlobStore._to_info(props).metadata == {"error": "", "status": "done"}
    assert AzureBlobStore._to_info(SimpleNamespace(**{**vars(props), "metadata": None})).metadata == {}


@pytest.fixture
def azurite(monkeypatch):
    from docintel.config import reset_settings_cache

    monkeypatch.setenv("STORAGE_BACKEND", "azure")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", AZURITE)
    for name, value in (("CONTAINER_UPLOADS", "uploads"), ("CONTAINER_RESULTS", "results"), ("CONTAINER_CONFIG", "config")):
        monkeypatch.setenv(name, f"{value}-{uuid.uuid4().hex[:8]}")  # a fresh set of containers per test
    reset_settings_cache()
    yield
    reset_settings_cache()


@needs_azurite
def test_store_contract(azurite):
    from docintel.factory import get_blob_store

    store = get_blob_store()
    c = f"t{uuid.uuid4().hex[:10]}"
    etag = store.put_bytes(c, "a.json", b"1", metadata={"k": "v", "empty": ""}, if_none_match=True)
    with pytest.raises(PreconditionFailed):
        store.put_bytes(c, "a.json", b"2", if_none_match=True)
    with pytest.raises(PreconditionFailed):
        store.put_bytes(c, "a.json", b"2", if_match='"stale"')
    new = store.put_bytes(c, "a.json", b"2", if_match=etag)
    assert store.get_with_etag(c, "a.json") == (b"2", new)
    info = store.list_info(c)[0]
    assert info.metadata == {"k": "v", "empty": ""}  # kept by a conditional rewrite, and "" stays text
    assert store.get_info(c, "a.json").metadata == {"k": "v", "empty": ""}
    store.put_bytes(c, "dir/b.bin", b"xyz")
    assert store.list(c, prefix="dir/") == ["dir/b.bin"]
    assert b"".join(store.iter_chunks(c, "dir/b.bin")) == b"xyz"
    assert store.delete(c, "a.json") and not store.delete(c, "a.json")
    with pytest.raises(FileNotFoundError):
        store.get_bytes(c, "a.json")


@needs_azurite
def test_documents_batches_and_budget_on_blob_storage(azurite):
    from docintel import batches, jobs, results, samples
    from docintel.pages import budget_usage

    sample = samples.get_sample("inv-02-us-logistics")
    data = samples.sample_path(sample, "pdf").read_bytes()
    batch_id = results.new_id()
    batches.create(batch_id, name="Azurite", expected=2, owner="o", owner_role="Admin", model_id="prebuilt-invoice",
                   selection=["VendorName"], include_images=False)
    ids = [jobs.submit_file(f"{i}.pdf", data, model_id="prebuilt-invoice", fields=["VendorName"], owner="o",
                            owner_role="Admin", batch_id=batch_id, start=False)["id"] for i in range(2)]
    assert jobs.recover() == ids or set(jobs.recover()) == set(ids)  # restart recovery lists the documents
    assert jobs.claim(ids[0]) is not None and jobs.claim(ids[0]) is None  # a claim is exclusive on real ETags
    results.update(ids[0], lambda r: r.update(status="queued", claimed_by=None))
    assert [jobs.process(i) for i in ids] == ["done", "done"]
    assert {r["status"] for r in results.list_summaries()} == {"done"}  # what History reads
    assert results.summary(ids[0])["error"] == ""
    batches.finish_upload(batch_id, 2)
    assert batches.detail(batch_id)[0]["complete"] and batches.list_all()[0]["name"] == "Azurite"
    assert budget_usage(200)["used"] == 2
    assert batches.delete(batch_id) == 2 and results.list_summaries() == []
