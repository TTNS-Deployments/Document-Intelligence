"""Field catalog (Config/fields.yaml) and presets (Config/presets.yaml plus Admin changes in the config container)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import get_settings
from .factory import get_blob_store

PRESETS_BLOB = "presets.json"


class CatalogError(ValueError):
    """Invalid model, field or preset."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str
    description: str = ""
    group: str = ""
    items: tuple["Field", ...] = ()
    item_type: str = ""
    derived: bool = False

    @property
    def is_table(self) -> bool:
        """An array of objects: shown as a table with one column per sub-field."""
        return self.type == "array" and bool(self.items)

    def to_dict(self) -> dict:
        d = {"name": self.name, "label": self.label, "type": self.type, "description": self.description,
             "group": self.group, "derived": self.derived, "is_table": self.is_table}
        if self.items:
            d["items"] = [i.to_dict() for i in self.items]
        if self.item_type:
            d["item_type"] = self.item_type
        return d


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    description: str
    enabled: bool
    unavailable_reason: str
    groups: tuple[tuple[str, tuple[Field, ...]], ...]
    fields: dict = field(default_factory=dict, compare=False, hash=False)

    def field(self, name: str) -> Field:
        try:
            return self.fields[name]
        except KeyError:
            raise CatalogError(f"{name} is not a field of {self.id}") from None

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description, "enabled": self.enabled,
                "unavailable_reason": self.unavailable_reason,
                "groups": [{"name": g, "fields": [f.to_dict() for f in fs]} for g, fs in self.groups]}


@dataclass(frozen=True)
class Catalog:
    api_version: str
    default_model: str
    models: dict

    def model(self, model_id: str) -> Model:
        try:
            return self.models[model_id]
        except KeyError:
            raise CatalogError(f"Unknown model {model_id!r}") from None

    def enabled_model(self, model_id: str) -> Model:
        model = self.model(model_id)
        if not model.enabled:
            raise CatalogError(f"{model.label} ({model.id}) is not available: {model.unavailable_reason}")
        return model

    def validate_selection(self, model_id: str, names) -> list[str]:
        """Known field names in catalog order, without duplicates. Raises on unknown names or an empty list."""
        model = self.model(model_id)
        wanted = {n.strip() for n in names if n and n.strip()}
        unknown = sorted(wanted - set(model.fields))
        if unknown:
            raise CatalogError(f"Unknown field(s) for {model.label}: {', '.join(unknown)}")
        if not wanted:
            raise CatalogError("Choose at least one field")
        return [n for n in model.fields if n in wanted]


def _field(raw: dict, group: str) -> Field:
    items = tuple(_field(i, group) for i in raw.get("items", []) or [])
    return Field(name=raw["name"], label=raw.get("label", raw["name"]), type=raw.get("type", "string"),
                 description=raw.get("description", ""), group=group, items=items,
                 item_type=raw.get("item_type", ""), derived=bool(raw.get("derived", False)))


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    config_dir = get_settings().config_dir
    if not config_dir or not (Path(config_dir) / "fields.yaml").is_file():
        raise RuntimeError("Config/fields.yaml not found (set DOCINTEL_CONFIG_DIR)")
    raw = yaml.safe_load((Path(config_dir) / "fields.yaml").read_text())
    models = {}
    for model_id, spec in raw["models"].items():
        groups = []
        fields = {}
        for g in spec["groups"]:
            fs = tuple(_field(f, g["name"]) for f in g["fields"])
            groups.append((g["name"], fs))
            for f in fs:
                if f.name in fields:
                    raise RuntimeError(f"Duplicate field {f.name} in {model_id}")
                fields[f.name] = f
        models[model_id] = Model(id=model_id, label=spec.get("label", model_id), description=spec.get("description", ""),
                                 enabled=bool(spec.get("enabled", True)),
                                 unavailable_reason=(spec.get("unavailable_reason") or "").strip(),
                                 groups=tuple(groups), fields=fields)
    return Catalog(api_version=str(raw.get("api_version", "2024-11-30")),
                   default_model=raw.get("default_model", next(iter(models))), models=models)


# --------------------------------------------------------------------------------------------- presets

_SLUG = re.compile(r"[^a-z0-9]+")


def _builtin_presets() -> dict:
    config_dir = get_settings().config_dir
    path = Path(config_dir) / "presets.yaml" if config_dir else None
    if not path or not path.is_file():
        return {}
    return (yaml.safe_load(path.read_text()) or {}).get("presets", {})


def _overrides() -> dict:
    s = get_settings()
    return get_blob_store().get_json_or_none(s.container_config, PRESETS_BLOB) or {"models": {}}


def get_presets(model_id: str) -> list[dict]:
    """Presets for one model: built-in ones (unless hidden or replaced) followed by Admin-created ones."""
    catalog = load_catalog()
    model = catalog.model(model_id)
    over = _overrides().get("models", {}).get(model_id, {})
    hidden = set(over.get("hidden", []))
    custom = {p["id"]: p for p in over.get("custom", [])}
    out = []
    for p in _builtin_presets().get(model_id, []):
        if p["id"] in hidden:
            continue
        if p["id"] in custom:
            out.append({**custom.pop(p["id"]), "builtin": True})
        else:
            out.append({"id": p["id"], "name": p["name"], "fields": list(p["fields"]),
                        "default": bool(p.get("default")), "builtin": True})
    out.extend({**p, "builtin": False} for p in custom.values())
    for p in out:  # drop names that are no longer in the catalog instead of failing
        p["fields"] = [f for f in p["fields"] if f in model.fields]
        p.setdefault("default", False)
    return out


def default_fields(model_id: str) -> list[str]:
    presets = get_presets(model_id)
    chosen = next((p for p in presets if p.get("default")), presets[0] if presets else None)
    if chosen and chosen["fields"]:
        return chosen["fields"]
    model = load_catalog().model(model_id)
    return list(model.fields)


def save_preset(model_id: str, name: str, fields, preset_id: str | None = None, *, default: bool = False) -> dict:
    catalog = load_catalog()
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise CatalogError("A preset needs a name of 1 to 60 characters")
    selection = catalog.validate_selection(model_id, fields)
    preset_id = preset_id or _SLUG.sub("-", name.lower()).strip("-")[:40] or "preset"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", preset_id):
        raise CatalogError("Invalid preset id")

    def change(over: dict) -> None:
        model_over = over.setdefault("models", {}).setdefault(model_id, {"custom": [], "hidden": []})
        custom = [p for p in model_over.setdefault("custom", []) if p["id"] != preset_id]
        if default:
            for p in custom:
                p["default"] = False
        custom.append({"id": preset_id, "name": name, "fields": selection, "default": default})
        model_over["custom"] = custom
        model_over["hidden"] = [h for h in model_over.setdefault("hidden", []) if h != preset_id]

    _update_overrides(change)
    return {"id": preset_id, "name": name, "fields": selection, "default": default}


def delete_preset(model_id: str, preset_id: str) -> None:
    load_catalog().model(model_id)
    builtin_ids = {p["id"] for p in _builtin_presets().get(model_id, [])}

    def change(over: dict) -> None:
        model_over = over.setdefault("models", {}).setdefault(model_id, {"custom": [], "hidden": []})
        before = len(model_over.get("custom", []))
        model_over["custom"] = [p for p in model_over.get("custom", []) if p["id"] != preset_id]
        if preset_id in builtin_ids:
            model_over.setdefault("hidden", [])
            if preset_id not in model_over["hidden"]:
                model_over["hidden"].append(preset_id)
        elif len(model_over["custom"]) == before:
            raise CatalogError(f"No preset {preset_id!r}")

    _update_overrides(change)


def _update_overrides(change) -> None:
    """Read-modify-write of presets.json with optimistic concurrency (retries when two Admins save at once)."""
    from .storage import PreconditionFailed

    s = get_settings()
    store = get_blob_store()
    for _ in range(5):
        try:
            over, etag = store.get_json_with_etag(s.container_config, PRESETS_BLOB)
        except FileNotFoundError:
            over, etag = {"models": {}}, None
        change(over)
        try:
            if etag is None:
                store.put_json(s.container_config, PRESETS_BLOB, over, if_none_match=True)
            else:
                store.put_json(s.container_config, PRESETS_BLOB, over, if_match=etag)
            return
        except PreconditionFailed:
            continue
    raise RuntimeError("Could not save presets (too many concurrent changes); try again")
