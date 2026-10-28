"""Helpers shared by the page views and the API: records, the review view, the catalog for the browser."""

from django.http import Http404

from docintel import catalog, normalize, pages, results, samples, settings_store


def runtime():
    return settings_store.get_runtime_settings()


def threshold() -> float:
    return runtime()["review_threshold"]


def get_record(doc_id: str) -> dict:
    try:
        return results.get(doc_id)
    except results.NotFound:
        raise Http404("No such document") from None


def get_summary(doc_id: str) -> dict:
    try:
        return results.summary(doc_id)
    except results.NotFound:
        raise Http404("No such document") from None


def review_context(record: dict, user) -> dict:
    """Everything the review templates need for one document."""
    rt = runtime()
    model = catalog.load_catalog().model(record["model_id"])
    view = normalize.build_view(record, rt["review_threshold"]) if record["status"] == "done" else None
    return {
        "doc": record, "view": view, "model": model, "threshold": rt["review_threshold"],
        "can_delete": user.can_delete(record.get("owner", "")),
        "selection": record.get("selection") or [],
        "viewer": {
            "id": record["id"], "kind": record.get("kind"), "file_url": f"/api/documents/{record['id']}/file",
            "pages": view["pages"] if view else [],
        },
    }


def catalog_payload() -> dict:
    """Models, field groups and presets for the field picker in the browser."""
    c = catalog.load_catalog()
    return {
        "api_version": c.api_version,
        "default_model": c.default_model,
        "models": [{**m.to_dict(), "presets": catalog.get_presets(m.id)} for m in c.models.values()],
    }


def sample_list() -> list[dict]:
    out = []
    for s in samples.list_samples():
        out.append({"id": s["id"], "title": s["title"], "description": s.get("description", ""),
                    "model_id": s["model_id"], "variants": list(s["variants"]), "pages": len(s["pages"])})
    return out


def budget() -> dict:
    return pages.budget_usage(runtime()["daily_page_limit"])
