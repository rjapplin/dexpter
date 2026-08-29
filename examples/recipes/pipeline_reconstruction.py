"""Recipe: reconstruct a pipeline from experiment links.

dexpter gives you direct neighbours via `db.links(id)`. These helpers build
on that to recover a whole linked pipeline and put it in run order.

Copy this into your project and adapt freely.

    python examples/recipes/pipeline_reconstruction.py
"""

import sys
import tempfile
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dexpter import Dexpter


def linked_component(db, start):
    """Every experiment reachable from `start` by following links (incl. start)."""
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for node in frontier:
            for neighbour in db.links(node):
                if neighbour not in seen:
                    seen.add(neighbour)
                    nxt.append(neighbour)
        frontier = nxt
    return seen


def ordered_pipeline(db, start):
    """The linked component of `start`, sorted by created_at (pipeline order)."""
    records = [db.get(exp_id) for exp_id in linked_component(db, start)]
    records.sort(key=lambda r: r["created_at"])
    return [r["id"] for r in records]


def all_edges(db):
    """Every link in the database as a sorted list of (id_a, id_b) pairs."""
    seen = set()
    for exp_id in db:
        for neighbour in db.links(exp_id):
            seen.add(tuple(sorted((exp_id, neighbour))))
    return sorted(seen)


def _demo():
    path = Path(tempfile.mkdtemp(prefix="dexpter_recipe_")) / "pipe.dexpter"
    db = Dexpter.init(path)

    db.log("data_sim", rows=1500)
    db.log("feat_eng", n_features=6, links=["data_sim"])
    db.log("training", model="logreg", links=["feat_eng"])
    db.log("eval", holdout_auc=0.80, links=["training"])

    print(f"db: {path}\n")
    print("edges                 :", all_edges(db))
    print("component from 'eval'  :", sorted(linked_component(db, "eval")))
    print("pipeline order         :", " -> ".join(ordered_pipeline(db, "eval")))


if __name__ == "__main__":
    _demo()
