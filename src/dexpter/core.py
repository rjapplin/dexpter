import hashlib
import json
import os
import tempfile
import warnings as _warnings
from datetime import datetime, timezone
from pathlib import Path

RESERVED_FIELDS = {"id", "created_at", "updated_at"}
_META_KEY = "__dexpter__"


class DexpterError(Exception):
    pass


class DexpterSealWarning(UserWarning):
    """Warned by load() when a sealed database was changed outside dexpter."""


class Dexpter:
    """A JSON-backed store of experiments, keyed by experiment id."""

    def __init__(self, path, data):
        self.path = Path(path)
        self._data = data
        meta = self._data.get(_META_KEY)
        if not isinstance(meta, dict):
            meta = {}
            self._data[_META_KEY] = meta
        meta.setdefault("required_fields", [])
        meta.setdefault("links", [])

    @classmethod
    def init(cls, path, required_fields=None, exist_ok=False, sealed=False):
        path = Path(path)
        if path.exists():
            if not exist_ok:
                raise DexpterError(f"'{path}' already exists. Pass exist_ok=True to reuse it.")
            return cls.load(path)

        required_fields = list(required_fields or [])
        bad = RESERVED_FIELDS & set(required_fields)
        if bad:
            raise DexpterError(f"Cannot require reserved field(s): {sorted(bad)}")

        meta = {"required_fields": required_fields, "links": []}
        if sealed:
            meta["sealed"] = True
        db = cls(path, {_META_KEY: meta})
        db._save()
        return db

    @classmethod
    def load(cls, path, validate=True):
        path = Path(path)
        if not path.exists():
            raise DexpterError(f"'{path}' does not exist. Call Dexpter.init() first.")
        with open(path) as f:
            data = json.load(f)

        if validate:
            report = _validate_data(data)
            if report["errors"]:
                raise DexpterError(
                    f"'{path}' is structurally broken: "
                    + "; ".join(report["errors"])
                    + "  (pass validate=False to load anyway, or run `dexpter check`)"
                )

        db = cls(path, data)

        meta = data.get(_META_KEY) if isinstance(data, dict) else None
        if (
            isinstance(meta, dict)
            and meta.get("sealed")
            and isinstance(meta.get("content_hash"), str)
            and _canonical_hash(data) != meta["content_hash"]
        ):
            _warnings.warn(
                f"'{path}' has changed outside dexpter since it was last sealed "
                f"(content hash mismatch). Call .seal() again to accept the "
                f"current contents.",
                DexpterSealWarning,
                stacklevel=2,
            )
        return db

    @classmethod
    def validate(cls, path):
        """Inspect a database file for problems introduced outside the API.

        Returns {"errors": [...], "warnings": [...], "seal": <str>}:
          errors   -- structurally broken; load(validate=True) will refuse it
          warnings -- usable but sloppy (hand-edited, lost an invariant)
          seal     -- "ok" | "mismatch" | "unsealed" | "unknown"
        Only raises if the file is missing.
        """
        path = Path(path)
        if not path.exists():
            raise DexpterError(f"'{path}' does not exist.")
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return {"errors": [f"not valid JSON: {e}"], "warnings": [], "seal": "unknown"}

        report = _validate_data(data)

        seal = "unsealed"
        meta = data.get(_META_KEY) if isinstance(data, dict) else None
        if isinstance(meta, dict) and meta.get("sealed"):
            stored = meta.get("content_hash")
            if not isinstance(stored, str):
                report["warnings"].append("database is sealed but has no content_hash")
                seal = "unknown"
            elif stored == _canonical_hash(data):
                seal = "ok"
            else:
                seal = "mismatch"
        report["seal"] = seal
        return report

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

    # -- sealing (opt-in tamper-evidence) -----------------------------------

    @property
    def sealed(self):
        return bool(self._data[_META_KEY].get("sealed"))

    def seal(self):
        """Turn on tamper-evidence. From now on every save stores a hash of
        the contents, and load() warns (DexpterSealWarning) if the file was
        changed outside dexpter. Call again at any time to re-baseline after
        deliberate external edits.
        """
        self._data[_META_KEY]["sealed"] = True
        self._save()

    def unseal(self):
        """Turn tamper-evidence back off and drop the stored hash."""
        meta = self._data[_META_KEY]
        meta.pop("sealed", None)
        meta.pop("content_hash", None)
        self._save()

    def verify_seal(self):
        """True if sealed and the contents match the stored hash, False if
        sealed and they don't, None if the database isn't sealed.
        """
        meta = self._data[_META_KEY]
        if not meta.get("sealed"):
            return None
        return meta.get("content_hash") == _canonical_hash(self._data)

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
        meta = self._data[_META_KEY]
        meta.pop("content_hash", None)
        if meta.get("sealed"):
            meta["content_hash"] = _canonical_hash(self._data)

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


def _is_iso(value):
    if not isinstance(value, str):
        return False
    # A trailing 'Z' isn't accepted by fromisoformat before Python 3.11;
    # normalize it so validation behaves the same on every supported version.
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _canonical_hash(data):
    """SHA-256 of the database contents in a canonical form: reformatting
    (whitespace, key order) does not change it, but edited values do. The
    stored `content_hash` field itself is excluded.
    """
    payload = dict(data)
    meta = payload.get(_META_KEY)
    if isinstance(meta, dict):
        payload[_META_KEY] = {k: v for k, v in meta.items() if k != "content_hash"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_data(data):
    """Structural check of a parsed database. Returns {"errors", "warnings"}.

    errors   -- the file no longer matches dexpter's shape and the API may
                misbehave on it
    warnings -- the file still works but an invariant the API maintains was
                lost (usually a careless hand-edit)
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        return {"errors": ["top-level value is not a JSON object"], "warnings": []}

    meta = data.get(_META_KEY)
    if meta is None:
        warnings.append(f"missing '{_META_KEY}' metadata block")
        meta = {}
    elif not isinstance(meta, dict):
        errors.append(f"'{_META_KEY}' is not an object")
        meta = {}

    required_fields = meta.get("required_fields", [])
    if not isinstance(required_fields, list) or not all(
        isinstance(f, str) for f in required_fields
    ):
        errors.append("'required_fields' is not a list of strings")
        required_fields = []

    raw_links = meta.get("links", [])
    links = []
    if not isinstance(raw_links, list):
        errors.append("'links' is not a list")
    else:
        for i, edge in enumerate(raw_links):
            if (
                isinstance(edge, list)
                and len(edge) == 2
                and all(isinstance(x, str) for x in edge)
            ):
                links.append(edge)
            else:
                errors.append(
                    f"links[{i}] is not an [id_a, id_b] pair of strings: {edge!r}"
                )

    content_hash = meta.get("content_hash")
    if content_hash is not None and not isinstance(content_hash, str):
        errors.append("'content_hash' is not a string")

    experiment_ids = [k for k in data if k != _META_KEY]

    for exp_id in experiment_ids:
        record = data[exp_id]
        if not isinstance(record, dict):
            errors.append(f"experiment '{exp_id}' is not an object")
            continue

        if "id" not in record:
            warnings.append(f"experiment '{exp_id}' is missing 'id'")
        elif record["id"] != exp_id:
            errors.append(
                f"experiment '{exp_id}' has a mismatched 'id' field: {record['id']!r}"
            )

        for ts_field in ("created_at", "updated_at"):
            if ts_field not in record:
                warnings.append(f"experiment '{exp_id}' is missing '{ts_field}'")
            elif not _is_iso(record[ts_field]):
                warnings.append(
                    f"experiment '{exp_id}' has an unparseable '{ts_field}': "
                    f"{record[ts_field]!r}"
                )

        if (
            _is_iso(record.get("created_at"))
            and _is_iso(record.get("updated_at"))
            and record["updated_at"] < record["created_at"]
        ):
            warnings.append(f"experiment '{exp_id}' has 'updated_at' before 'created_at'")

        missing = [f for f in required_fields if f not in record]
        if missing:
            warnings.append(
                f"experiment '{exp_id}' is missing required field(s): "
                f"{', '.join(sorted(missing))}"
            )

    known = set(experiment_ids)
    reported = set()
    for edge in links:
        for endpoint in edge:
            if endpoint not in known and endpoint not in reported:
                reported.add(endpoint)
                warnings.append(f"link references unknown experiment '{endpoint}'")

    return {"errors": errors, "warnings": warnings}
