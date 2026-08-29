"""Recipe: diff two experiment records.

Shows what changed between two experiments -- like `git diff`, but for
dexpter records instead of files. Works even when the two records don't
carry the same fields, which is the common case during exploratory work.

Copy this into your project and adapt freely.

    python examples/recipes/experiment_diff.py
"""

import sys
import tempfile
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dexpter import Dexpter

AUTO_FIELDS = frozenset({"id", "created_at", "updated_at"})


def diff(db, id_a, id_b, ignore=AUTO_FIELDS):
    """Return {changed, only_in_a, only_in_b, unchanged} for two experiments.

    `changed` maps field -> (value_in_a, value_in_b). Nested dicts/lists are
    compared by equality only -- no recursion into what changed inside them.
    """
    a, b = db.get(id_a), db.get(id_b)
    if a is None:
        raise KeyError(id_a)
    if b is None:
        raise KeyError(id_b)
    a = {k: v for k, v in a.items() if k not in ignore}
    b = {k: v for k, v in b.items() if k not in ignore}

    changed, only_in_a, only_in_b, unchanged = {}, {}, {}, []
    for key in sorted(set(a) | set(b)):
        if key in a and key in b:
            if a[key] == b[key]:
                unchanged.append(key)
            else:
                changed[key] = (a[key], b[key])
        elif key in a:
            only_in_a[key] = a[key]
        else:
            only_in_b[key] = b[key]
    return {
        "changed": changed,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "unchanged": unchanged,
    }


def format_diff(result, label_a="a", label_b="b"):
    lines = []
    for field, (old, new) in sorted(result["changed"].items()):
        lines.append(f"  ~ {field}: {old!r} -> {new!r}")
    for field, value in sorted(result["only_in_a"].items()):
        lines.append(f"  - {field}: {value!r}   (only in {label_a})")
    for field, value in sorted(result["only_in_b"].items()):
        lines.append(f"  + {field}: {value!r}   (only in {label_b})")
    if result["unchanged"]:
        lines.append(f"  = unchanged: {', '.join(result['unchanged'])}")
    return "\n".join(lines) if lines else "(identical)"


def _demo():
    path = Path(tempfile.mkdtemp(prefix="dexpter_recipe_")) / "diff.dexpter"
    db = Dexpter.init(path)

    db.log("feat_set_v3", n_features=42, encoder="target", val_auc=0.81, notes="baseline")
    db.log(
        "feat_set_v4",
        n_features=47,
        encoder="target",
        val_auc=0.84,
        notes="added interaction feats",
        leakage_check="passed",
    )

    result = diff(db, "feat_set_v3", "feat_set_v4")
    print(f"db: {path}\n")
    print("feat_set_v3 -> feat_set_v4")
    print(format_diff(result, "feat_set_v3", "feat_set_v4"))


if __name__ == "__main__":
    _demo()
