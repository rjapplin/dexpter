"""Recipe: track when each field first appeared on an experiment.

dexpter has no built-in field history -- and doesn't need one, because you
can layer it on in a few lines. This keeps a `field_history` dict on the
record, mapping field name -> ISO timestamp of the log() call that first
set it.

Use `log_with_history(db, id, **fields)` in place of `db.log(...)`. Fields
written through a plain `db.log` won't be recorded, so pick one entry point
and stick with it for a given database.

Copy this into your project and adapt freely.

    python examples/recipes/field_history.py
"""

import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dexpter import Dexpter

HISTORY_FIELD = "field_history"


def log_with_history(db, experiment_id, **fields):
    """Like db.log(), but also records the first-seen time of every field."""
    fields.pop(HISTORY_FIELD, None)
    existing = db.get(experiment_id) or {}
    history = dict(existing.get(HISTORY_FIELD, {}))
    now = datetime.now(timezone.utc).isoformat()
    for key in fields:
        history.setdefault(key, now)  # keep the earliest time; ignore re-logs
    return db.log(experiment_id, **{HISTORY_FIELD: history}, **fields)


def _demo():
    path = Path(tempfile.mkdtemp(prefix="dexpter_recipe_")) / "hist.dexpter"
    db = Dexpter.init(path)

    log_with_history(db, "run1", lr=0.01, model="resnet18")
    time.sleep(0.01)
    log_with_history(db, "run1", accuracy=0.91)              # new field, later
    time.sleep(0.01)
    log_with_history(db, "run1", accuracy=0.93, epochs=12)   # epochs new; accuracy unchanged

    record = db.get("run1")
    print(f"db: {path}\n")
    for field, first_seen in sorted(record[HISTORY_FIELD].items()):
        print(f"  {field:10} first seen {first_seen}")


if __name__ == "__main__":
    _demo()
