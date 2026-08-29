"""Recipe: transitive walking over experiment links.

`db.links(id)` gives you direct neighbours only. These helpers do the
breadth-first walk on top -- everything reachable, hop distances, bounded
neighbourhoods, and shortest paths between two experiments.

`walk()` is the primitive; the rest are one-liners over it. See
`pipeline_reconstruction.py` for using this to rebuild a pipeline in run
order.

Copy this into your project and adapt freely.

    python examples/recipes/link_traversal.py
"""

import sys
import tempfile
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dexpter import Dexpter


def walk(db, start, max_depth=None):
    """Yield (experiment_id, depth) for `start` and everything transitively
    linked to it, breadth-first. `start` comes first at depth 0. Stops after
    `max_depth` hops if given.
    """
    seen = {start}
    frontier = [start]
    depth = 0
    while frontier:
        for node in frontier:
            yield node, depth
        if max_depth is not None and depth >= max_depth:
            return
        depth += 1
        nxt = []
        for node in frontier:
            for neighbour in db.links(node):
                if neighbour not in seen:
                    seen.add(neighbour)
                    nxt.append(neighbour)
        frontier = nxt


def reachable(db, start, include_start=False):
    """The set of experiments transitively linked to `start`."""
    ids = {exp_id for exp_id, _ in walk(db, start)}
    if not include_start:
        ids.discard(start)
    return ids


def depths(db, start):
    """Map experiment_id -> hop count from `start` (`start` itself is 0)."""
    return {exp_id: d for exp_id, d in walk(db, start)}


def within(db, start, max_depth):
    """Sorted ids at most `max_depth` hops from `start` (excludes `start`)."""
    return sorted(
        exp_id for exp_id, d in walk(db, start, max_depth=max_depth) if exp_id != start
    )


def shortest_path(db, src, dst):
    """A shortest chain of ids from `src` to `dst` along links, including both
    endpoints, or None if they aren't connected.
    """
    if src == dst:
        return [src]
    prev = {src: None}
    frontier = [src]
    while frontier:
        nxt = []
        for node in frontier:
            for neighbour in db.links(node):
                if neighbour in prev:
                    continue
                prev[neighbour] = node
                if neighbour == dst:
                    path = [dst]
                    while prev[path[-1]] is not None:
                        path.append(prev[path[-1]])
                    return list(reversed(path))
                nxt.append(neighbour)
        frontier = nxt
    return None


def _demo():
    path = Path(tempfile.mkdtemp(prefix="dexpter_recipe_")) / "graph.dexpter"
    db = Dexpter.init(path)

    #            raw
    #           /   \
    #      feat_a   feat_b
    #        |         |
    #     train_1   train_2
    #           \   /
    #           eval
    db.log("raw", rows=5000)
    db.log("feat_a", kind="counts", links=["raw"])
    db.log("feat_b", kind="embeddings", links=["raw"])
    db.log("train_1", model="logreg", links=["feat_a"])
    db.log("train_2", model="gbm", links=["feat_b"])
    db.log("eval", metric="auc", links=["train_1", "train_2"])

    print(f"db: {path}\n")
    print("walk from 'eval'    :", [f"{i}({d})" for i, d in walk(db, "eval")])
    print("reachable from 'eval':", sorted(reachable(db, "eval")))
    print("depths from 'raw'   :", depths(db, "raw"))
    print("within 2 hops of raw:", within(db, "raw", 2))
    print("path raw -> eval    :", " -> ".join(shortest_path(db, "raw", "eval")))
    print("path feat_a -> feat_b:", " -> ".join(shortest_path(db, "feat_a", "feat_b")))


if __name__ == "__main__":
    _demo()
