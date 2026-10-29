from datetime import datetime, timedelta, timezone

import pytest

from docintel import batches, jobs, results, samples


def sample_bytes(sample_id):
    s = samples.get_sample(sample_id)
    return samples.sample_path(s, samples.preferred_variant(s)).read_bytes()


def add(batch_id, sample_id, process=True):
    rec = jobs.submit_file(f"{sample_id}.pdf", sample_bytes(sample_id), model_id="prebuilt-invoice",
                           fields=["VendorName", "PurchaseOrder", "InvoiceTotal"], owner="o", owner_role="Admin",
                           batch_id=batch_id, start=False)
    if process:
        jobs.process(rec["id"])
    return rec


def new_batch(expected=3, name="October invoices"):
    batch_id = results.new_id()
    batches.create(batch_id, name=name, expected=expected, owner="o", owner_role="Admin",
                   model_id="prebuilt-invoice", selection=["VendorName"], include_images=False)
    return batch_id


def test_batch_runs_in_the_background_and_completes():
    batch_id = new_batch(expected=3)
    add(batch_id, "inv-01-gst-software")
    summary, rows = batches.detail(batch_id)
    assert summary["status"] == "uploading" and not summary["complete"] and summary["arrived"] == 1
    add(batch_id, "inv-02-us-logistics", process=False)
    add(batch_id, "inv-03-uk-interiors", process=False)
    batches.finish_upload(batch_id, 3)
    summary, rows = batches.detail(batch_id)
    assert summary["status"] == "running" and summary["queued"] == 2 and not summary["complete"]
    for r in rows:
        jobs.process(r["id"])
    summary, rows = batches.detail(batch_id)
    assert summary["status"] == "complete" and summary["complete"] and summary["percent"] == 100
    assert summary["done"] == 3 and summary["documents_to_review"] == 1  # inv-01: purchase order at 0.76
    assert [r["filename"] for r in rows] == ["inv-01-gst-software.pdf", "inv-02-us-logistics.pdf",
                                             "inv-03-uk-interiors.pdf"]


def test_review_progress_follows_the_documents():
    batch_id = new_batch(expected=1)
    rec = add(batch_id, "inv-01-gst-software")
    batches.finish_upload(batch_id, 1)
    assert batches.detail(batch_id)[0]["fields_to_review"] == 1
    results.update(rec["id"], lambda r: r.__setitem__("reviewed", ["PurchaseOrder"]))
    assert batches.detail(batch_id)[0]["documents_to_review"] == 0


def test_interrupted_upload_completes_with_what_arrived():
    batch_id = new_batch(expected=5)
    add(batch_id, "inv-02-us-logistics")
    record = batches.get(batch_id)
    later = datetime.now(timezone.utc) + timedelta(minutes=batches.UPLOAD_IDLE_MINUTES + 1)
    summary = batches.summarise(record, results.batch(batch_id), now=later)
    assert summary["interrupted"] and summary["expected"] == 1 and summary["complete"]
    soon = batches.summarise(record, results.batch(batch_id))
    assert soon["status"] == "uploading" and not soon["complete"]


def test_list_rename_and_delete():
    a = new_batch(expected=1, name="  First   batch ")
    add(a, "inv-02-us-logistics")
    b = new_batch(expected=1, name="")
    assert batches.get(a)["name"] == "First batch"
    assert batches.get(b)["name"].startswith("Upload of ")
    single = jobs.submit_file("x.pdf", sample_bytes("inv-03-uk-interiors"), model_id="prebuilt-invoice",
                              fields=["VendorName"], owner="o", owner_role="User", start=False)
    listed = batches.list_all()
    assert [x["id"] for x in listed] == [b, a]  # newest first; single uploads have no batch record
    assert results.list_summaries()[0]["id"] == single["id"]  # batch records are not documents
    batches.rename(a, "Renamed")
    assert batches.get(a)["name"] == "Renamed"
    with pytest.raises(ValueError):
        batches.rename(a, "   ")
    assert batches.delete(a) == 1
    with pytest.raises(batches.BatchNotFound):
        batches.get(a)
    assert all(r["batch_id"] != a for r in results.list_summaries())
    with pytest.raises(batches.BatchNotFound):
        batches.get("../x")
