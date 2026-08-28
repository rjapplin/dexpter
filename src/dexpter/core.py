import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RESERVED_FIELDS = {"id", "created_at", "updated_at"}
_META_KEY = "__dexpter__"


class DexpterError(Exception):
    pass


class Dexpter:
    """A JSON-backed store of experiments, keyed by experiment id."""

    def __init__(self, path, data):
        self.path = Path(path)
        self._data = data
        meta = self._data.setdefault(_META_KEY, {})
        meta.setdefault("required_fields", [])
        meta.setdefault("links", [])

    @classmethod
    def init(cls, path, required_fields=None, exist_ok=False):
        path = Path(path)
        if path.exists():
            if not exist_ok:
                raise DexpterError(f"'{path}' already exists. Pass exist_ok=True to reuse it.")
            return cls.load(path)

        required_fields = list(required_fields or [])
        bad = RESERVED_FIELDS & set(required_fields)
        if bad:
            raise DexpterError(f"Cannot require reserved field(s): {sorted(bad)}")

        data = {_META_KEY: {"required_fields": required_fields, "links": []}}
        db = cls(path, data)
        db._save()
        return db

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            raise DexpterError(f"'{path}' does not exist. Call Dexpter.init() first.")
        with open(path) as f:
            data = json.load(f)
        return cls(path, data)

    @property
    def required_fields(self):
        return list(self._data[_META_KEY]["required_fields"])

    def set_required_fields(self, required_fields):
        """Replace the set of required fields. Does not touch existing records,
        so this can leave older experiments non-compliant with the new rules.
        Returns {experiment_id: [missing_field, ...]} for any that now fall short.
        """
        required_fields = list(required_fields)
        bad = RESERVED_FIELDS & set(required_fields)
        if bad:
            raise DexpterError(f"Cannot require reserved field(s): {sorted(bad)}")

        self._data[_META_KEY]["required_fields"] = required_fields
        self._save()

        gaps = {}
        for exp_id, record in self.experiments.items():
            missing = [f for f in required_fields if f not in record]
            if missing:
                gaps[exp_id] = missing
        return gaps

    def log(self, experiment_id, **fields):
        if experiment_id == _META_KEY:
            raise DexpterError(f"'{experiment_id}' is a reserved id")

        link_targets = fields.pop("links", None)
        if isinstance(link_targets, str):
            link_targets = [link_targets]
        link_targets = list(link_targets or [])

        # Validate link targets before touching any state, so a bad target
        # can't leave a half-written record behind.
        for target in link_targets:
            if target == experiment_id:
                raise DexpterError(f"Cannot link '{experiment_id}' to itself")
            if target == _META_KEY or target not in self._data:
                raise DexpterError(f"Cannot link to '{target}': no such experiment")

        bad = RESERVED_FIELDS & fields.keys()
        if bad:
            raise DexpterError(f"Cannot set reserved field(s) directly: {sorted(bad)}")

        now = datetime.now(timezone.utc).isoformat()
        record = dict(self._data.get(experiment_id, {}))
        created_at = record.get("created_at", now)

        record.update(fields)
        record["id"] = experiment_id
        record["created_at"] = created_at
        record["updated_at"] = now

        missing = [f for f in self.required_fields if f not in record]
        if missing:
            raise DexpterError(f"Missing required field(s) for '{experiment_id}': {sorted(missing)}")

        self._data[experiment_id] = record
        for target in link_targets:
            self._add_edge(experiment_id, target)
        self._save()
        return record

    def get(self, experiment_id):
        record = self._data.get(experiment_id)
        return dict(record) if record is not None else None

    def delete(self, experiment_id):
        if experiment_id == _META_KEY or experiment_id not in self._data:
            raise DexpterError(f"No experiment '{experiment_id}' found")
        del self._data[experiment_id]
        links = self._data[_META_KEY]["links"]
        links[:] = [edge for edge in links if experiment_id not in edge]
        self._save()

    # -- linking --------------------------------------------------------------

    def link(self, a, b):
        """Create a symmetric link between two existing experiments. Idempotent."""
        if self._add_edge(a, b):
            self._save()

    def unlink(self, a, b):
        """Remove the link between two experiments. No error if it wasn't there."""
        edge = sorted([a, b])
        links = self._data[_META_KEY]["links"]
        if edge in links:
            links.remove(edge)
            self._save()

    def links(self, experiment_id):
        """Return the sorted ids of experiments linked to this one ([] if none)."""
        out = set()
        for a, b in self._data[_META_KEY]["links"]:
            if a == experiment_id:
                out.add(b)
            elif b == experiment_id:
                out.add(a)
        return sorted(out)

    def _add_edge(self, a, b):
        """Insert a normalized edge without saving. Returns True if it was new."""
        for exp_id in (a, b):
            if exp_id == _META_KEY or exp_id not in self._data:
                raise DexpterError(f"No experiment '{exp_id}' found")
        if a == b:
            raise DexpterError(f"Cannot link '{a}' to itself")

        edge = sorted([a, b])
        links = self._data[_META_KEY]["links"]
        if edge in links:
            return False
        links.append(edge)
        links.sort()
        return True

    # ----------------------------------------------------------------------

    @property
    def experiments(self):
        return {k: dict(v) for k, v in self._data.items() if k != _META_KEY}

    def __contains__(self, experiment_id):
        return experiment_id != _META_KEY and experiment_id in self._data

    def __len__(self):
        return len(self._data) - 1

    def __iter__(self):
        return iter(k for k in self._data if k != _META_KEY)

    def _save(self):
        fd, tmp_path = tempfile.mkstemp(
            dir=self.path.parent or ".", prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            os.unlink(tmp_path)
            raise
