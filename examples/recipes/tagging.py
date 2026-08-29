"""Recipe: tag experiments and query by tag.

Tags live in a plain `tags` list on the record. dexpter has no query API, so
`find_by_tag` just scans `db.experiments` -- fine for the file sizes dexpter
is meant for.

Copy this into your project and adapt freely.

    python examples/recipes/tagging.py
"""

import sys
import tempfile
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dexpter import Dexpter

TAGS_FIELD = "tags"


def add_tags(db, experiment_id, *tags):
    rec = db.get(experiment_id)
    if rec is None:
        raise KeyError(experiment_id)
    merged = set(rec.get(TAGS_FIELD, [])) | set(tags)
    return db.log(experiment_id, **{TAGS_FIELD: sorted(merged)})


def remove_tags(db, experiment_id, *tags):
    rec = db.get(experiment_id)
    if rec is None:
        raise KeyError(experiment_id)
    remaining = set(rec.get(TAGS_FIELD, [])) - set(tags)
    return db.log(experiment_id, **{TAGS_FIELD: sorted(remaining)})


def find_by_tag(db, *tags, match="any"):
    """Return the ids of experiments carrying these tags.

    match="any" (default): experiment has at least one of `tags`.
    match="all":            experiment has every one of `tags`.
    """
    want = set(tags)
    hits = []
    for exp_id, rec in db.experiments.items():
        have = set(rec.get(TAGS_FIELD, []))
        matched = (want <= have) if match == "all" else bool(want & have)
        if matched:
            hits.append(exp_id)
    return sorted(hits)


def _demo():
    path = Path(tempfile.mkdtemp(prefix="dexpter_recipe_")) / "tags.dexpter"
    db = Dexpter.init(path)

    db.log("run_a", val_auc=0.81)
    db.log("run_b", val_auc=0.84)
    db.log("run_c", val_auc=0.79)

    add_tags(db, "run_a", "baseline", "keep")
    add_tags(db, "run_b", "keep", "tuned")
    add_tags(db, "run_c", "scratch")
    remove_tags(db, "run_c", "scratch")
    add_tags(db, "run_c", "baseline")

    print(f"db: {path}\n")
    print("tagged 'keep'      :", find_by_tag(db, "keep"))
    print("tagged 'baseline'  :", find_by_tag(db, "baseline"))
    print("tagged keep + tuned:", find_by_tag(db, "keep", "tuned", match="all"))


if __name__ == "__main__":
    _demo()
