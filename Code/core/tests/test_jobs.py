from datetime import datetime, timedelta, timezone

import pytest

from docintel import jobs, results, samples
from docintel.analyze import AnalyzeError
from docintel.catalog import CatalogError
from docintel.factory import get_analyzer, get_job_runner
from docintel.pages import BudgetExceeded, UploadRejected, budget_usage
from helpers import make_pdf, make_png


def submit(data=None, name="invoice.pdf", **kw):
    kw.setdefault("model_id", "prebuilt-invoice")
    kw.setdefault("fields", ["VendorName", "InvoiceId", "InvoiceTotal"])
    return jobs.submit_file(name, data if data is not None else make_pdf(2), owner="s1", owner_role="User",
                            start=False, **kw)


def sample_bytes(sample_id="inv-01-gst-software", variant="pdf"):
    s = samples.get_sample(sample_id)
    return samples.sample_path(s, variant).read_bytes()


class FlakyAnalyzer:
    def __init__(self, failures, error=None):
        self.failures = failures
        self.requests_made = 0
        self.error = error or AnalyzeError("throttled", "busy", transient=True, status=429)

    def analyze(self, data, model_id):
        self.requests_made += 1
        if self.requests_made <= self.failures:
            raise self.error
        return {"apiVersion": "2024-11-30", "modelId": model_id, "pages": [], "documents": []}


def test_submit_creates_queued_record_and_original():
    rec = submit(sample_bytes(), name="inv-01-gst-software.pdf")
    stored = results.get(rec["id"])
    assert stored["status"] == "queued" and stored["pages"] == 1 and stored["owner"] == "s1"
    assert results.read_original(stored) == sample_bytes()
    assert budget_usage(200)["used"] == 1  # pages counted before any call


def test_submit_refuses_before_storing():
    with pytest.raises(UploadRejected):
        submit(make_png(), name="x.pdf")
    with pytest.raises(CatalogError):
        submit(model_id="prebuilt-businessCard", fields=["Emails"])
    with pytest.raises(CatalogError):
        submit(fields=["NotAField"])
    assert results.list_summaries() == [] and budget_usage(200)["used"] == 0


def test_daily_budget_refuses_new_jobs(monkeypatch):
    monkeypatch.setenv("DAILY_PAGE_LIMIT", "3")
    from docintel.config import reset_settings_cache

    reset_settings_cache()
    submit(make_pdf(2))
    with pytest.raises(BudgetExceeded):
        submit(make_pdf(2))
    assert len(results.list_summaries()) == 1


def test_queued_processing_done():
    rec = submit(sample_bytes(), name="sample.pdf", fields=["VendorName", "PurchaseOrder", "InvoiceTotal"])
    assert jobs.process(rec["id"]) == "done"
    done = results.get(rec["id"])
    assert done["status"] == "done" and done["error"] is None and done["attempts"] == 1
    assert done["analysis"]["modelId"] == "prebuilt-invoice"
    assert done["mock"]["source"] == "sample"
    assert done["duration_ms"] >= 0 and done["claimed_by"] is None
    row = results.list_summaries()[0]
    assert row["status"] == "done" and row["review_count"] >= 1 and row["filename"] == "sample.pdf"


def test_claim_is_exclusive():
    rec = submit()
    first = jobs.claim(rec["id"])
    assert first is not None and results.get(rec["id"])["status"] == "processing"
    assert jobs.claim(rec["id"]) is None  # duplicate claim refused
    assert jobs.process(rec["id"]) is None


def test_lost_race_on_claim(monkeypatch):
    """Two processes read the same queued record; only the first conditional write wins."""
    rec = submit()
    original = results.get_with_etag

    def stale_read(doc_id):
        record, etag = original(doc_id)
        if record["status"] == "queued":
            other = dict(record, status="processing", claimed_by="other:1:x")
            results.save(other, etag)  # the other process wins in between
        return record, etag

    monkeypatch.setattr(results, "get_with_etag", stale_read)
    assert jobs.claim(rec["id"]) is None


def test_transient_errors_are_retried_then_succeed(monkeypatch):
    flaky = FlakyAnalyzer(failures=2)
    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: flaky)
    sleeps = []
    rec = submit()
    assert jobs.process(rec["id"], sleep=sleeps.append) == "done"
    assert flaky.requests_made == 3 and sleeps == [0.0, 0.0]
    assert results.get(rec["id"])["attempts"] == 3


def test_backoff_grows_exponentially(monkeypatch):
    monkeypatch.setenv("ANALYZE_RETRY_BASE_SECONDS", "2")
    from docintel.config import reset_settings_cache

    reset_settings_cache()
    flaky = FlakyAnalyzer(failures=5)
    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: flaky)
    sleeps = []
    rec = submit()
    assert jobs.process(rec["id"], sleep=sleeps.append) == "failed"
    assert sleeps == [2.0, 4.0]  # 3 attempts by default
    err = results.get(rec["id"])["error"]
    assert err["code"] == "throttled" and "tried 3 times" in err["message"]


def test_permanent_error_fails_without_retry(monkeypatch):
    flaky = FlakyAnalyzer(failures=1, error=AnalyzeError("unsupported", "Could not read this file."))
    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: flaky)
    rec = submit()
    assert jobs.process(rec["id"], sleep=lambda s: None) == "failed"
    assert flaky.requests_made == 1
    assert results.get(rec["id"])["error"] == {"code": "unsupported", "message": "Could not read this file."}


def test_unexpected_exception_never_leaves_processing(monkeypatch):
    class Broken:
        def analyze(self, data, model_id):
            raise KeyError("boom")

    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: Broken())
    rec = submit()
    assert jobs.process(rec["id"]) == "failed"
    assert results.get(rec["id"])["error"]["code"] == "internal"


def test_mock_failure_hooks_and_retry():
    rec = submit(make_pdf(text="DOCINTEL-MOCK-FAIL"))
    assert jobs.process(rec["id"]) == "failed"
    assert results.get(rec["id"])["error"]["code"] == "unsupported"
    jobs.retry(rec["id"], start=False)
    again = results.get(rec["id"])
    assert again["status"] == "queued" and again["error"] is None
    assert budget_usage(200)["used"] == 2  # the retry counts the page again
    with pytest.raises(ValueError):
        jobs.retry(rec["id"], start=False)  # only failed jobs


def test_throttle_hook_exhausts_retries():
    rec = submit(make_pdf(text="DOCINTEL-MOCK-THROTTLE"))
    assert jobs.process(rec["id"], sleep=lambda s: None) == "failed"
    assert results.get(rec["id"])["error"]["code"] == "throttled"


def test_restart_recovery():
    queued = submit()
    stuck_here = submit()
    stuck_alive = submit()
    stuck_expired = submit()
    for rec, claimed_by, minutes in ((stuck_here, f"{jobs.instance_id()}:99999:dead", 10),
                                     (stuck_alive, "other-instance:1:abc", 10),
                                     (stuck_expired, "other-instance:2:def", -1)):
        r, etag = results.get_with_etag(rec["id"])
        r.update(status="processing", claimed_by=claimed_by,
                 claim_expires=(datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat())
        results.save(r, etag)
    requeued = set(jobs.recover())
    assert requeued == {queued["id"], stuck_here["id"], stuck_expired["id"]}
    assert results.get(stuck_alive["id"])["status"] == "processing"  # another live instance still owns it
    assert results.get(stuck_here["id"])["status"] == "queued"


def test_result_discarded_when_claim_was_taken_over(monkeypatch):
    rec = submit()

    class TakeOver:
        def analyze(self, data, model_id):
            r, etag = results.get_with_etag(rec["id"])
            r["claimed_by"] = "someone-else:1:x"
            results.save(r, etag)
            return {"pages": [], "documents": []}

    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: TakeOver())
    assert jobs.process(rec["id"]) is None
    assert results.get(rec["id"])["claimed_by"] == "someone-else:1:x"


def test_deleted_while_processing(monkeypatch):
    rec = submit()

    class DeleteFirst:
        def analyze(self, data, model_id):
            results.delete(rec["id"])
            return {"pages": [], "documents": []}

    monkeypatch.setattr("docintel.jobs.get_analyzer", lambda: DeleteFirst())
    assert jobs.process(rec["id"]) is None
    with pytest.raises(results.NotFound):
        results.get(rec["id"])


def test_worker_pool_runs_a_batch():
    runner = get_job_runner()
    ids = []
    for sid in ("inv-02-us-logistics", "inv-03-uk-interiors", "inv-06-au-consulting"):
        rec = jobs.submit_file(f"{sid}.pdf", sample_bytes(sid), model_id="prebuilt-invoice",
                               fields=["VendorName", "InvoiceTotal"], owner="s", owner_role="User", batch_id="b1")
        ids.append(rec["id"])
    assert runner.wait_idle(20)
    assert len(runner._workers) == 2
    assert [results.get(i)["status"] for i in ids] == ["done"] * 3
    assert [r["id"] for r in results.batch("b1")] == ids


def test_analyzer_is_mock_in_local_mode():
    assert type(get_analyzer()).__name__ == "MockAnalyzer"
