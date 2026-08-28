"""End-to-end dexpter demo: simulate -> feature-eng -> train -> evaluate.

Runs a tiny customer-churn pipeline in four stages, logging one experiment per
stage and linking each stage back to the one it consumed. Then it re-opens the
database from disk and walks the links to reconstruct the whole pipeline from
the evaluation node.

Pure standard library -- no numpy, pandas, or sklearn. Nothing imported here is
a dependency of the `dexpter` package itself; it's only needed to run this
script.

    python examples/pipeline_demo.py
"""

import json
import math
import random
import sys
import tempfile
import time
from pathlib import Path

try:
    from dexpter import Dexpter
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dexpter import Dexpter

TARGET = "churned"


# ----------------------------------------------------------------------------
# stage 1: simulate raw data
# ----------------------------------------------------------------------------
def simulate_data(out_path, n_rows, seed):
    rng = random.Random(seed)
    rows = []
    for _ in range(n_rows):
        age = rng.uniform(18, 70)
        income = rng.lognormvariate(10.5, 0.6)
        tenure_months = rng.uniform(0, 72)
        n_support_tickets = rng.randint(0, 12)

        logit = (
            -1.8
            + 0.030 * (40 - age)
            - 1.1e-5 * (income - 35000)
            - 0.045 * tenure_months
            + 0.26 * n_support_tickets
            + rng.gauss(0, 0.5)
        )
        churn = 1 if rng.random() < 1 / (1 + math.exp(-logit)) else 0

        rows.append(
            {
                "age": round(age, 2),
                "income": round(income, 2),
                "tenure_months": round(tenure_months, 2),
                "n_support_tickets": n_support_tickets,
                TARGET: churn,
            }
        )

    out_path.write_text(json.dumps(rows, indent=2))
    n_pos = sum(r[TARGET] for r in rows)
    return {
        "n_rows": len(rows),
        "n_pos": n_pos,
        "positive_rate": round(n_pos / len(rows), 4),
    }


# ----------------------------------------------------------------------------
# stage 2: feature engineering
# ----------------------------------------------------------------------------
def engineer_features(raw_path, out_path):
    raw = json.loads(raw_path.read_text())
    feats = []
    for r in raw:
        tenure = r["tenure_months"]
        feats.append(
            {
                "age": r["age"],
                "log_income": round(math.log(r["income"]), 4),
                "tenure_months": tenure,
                "n_support_tickets": r["n_support_tickets"],
                "tickets_per_month": round(r["n_support_tickets"] / (tenure + 1), 4),
                "is_new_customer": 1 if tenure < 6 else 0,
                TARGET: r[TARGET],
            }
        )
    out_path.write_text(json.dumps(feats, indent=2))
    feature_cols = [c for c in feats[0] if c != TARGET]
    return {
        "n_rows": len(feats),
        "feature_cols": feature_cols,
        "n_features": len(feature_cols),
    }


# ----------------------------------------------------------------------------
# stage 3: training -- plain-Python logistic regression, full-batch GD
# ----------------------------------------------------------------------------
def _sigmoid(z):
    if z < 0:
        e = math.exp(z)
        return e / (1.0 + e)
    return 1.0 / (1.0 + math.exp(-z))


def _split(rows, split_seed, holdout_frac):
    rows = list(rows)
    random.Random(split_seed).shuffle(rows)
    cut = int(len(rows) * (1 - holdout_frac))
    return rows[:cut], rows[cut:]


def _standardize(rows, cols):
    stats = {}
    for c in cols:
        vals = [r[c] for r in rows]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[c] = (mean, math.sqrt(var) or 1.0)
    return stats


def _matrix(rows, cols, stats):
    X, y = [], []
    for r in rows:
        X.append([(r[c] - stats[c][0]) / stats[c][1] for c in cols])
        y.append(r[TARGET])
    return X, y


def _accuracy(y_true, scores):
    correct = sum(1 for t, s in zip(y_true, scores) if int(s >= 0.5) == t)
    return correct / len(y_true)


def _auc(y_true, scores):
    pos = [s for s, t in zip(scores, y_true) if t == 1]
    neg = [s for s, t in zip(scores, y_true) if t == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(pos) * len(neg))


def train_model(features_path, model_path, lr, epochs, split_seed, holdout_frac):
    rows = json.loads(features_path.read_text())
    cols = [c for c in rows[0] if c != TARGET]
    train_rows, _ = _split(rows, split_seed, holdout_frac)

    stats = _standardize(train_rows, cols)
    X, y = _matrix(train_rows, cols, stats)
    n, d = len(X), len(cols)

    w = [0.0] * d
    b = 0.0
    loss = float("nan")
    for _ in range(epochs):
        dw = [0.0] * d
        db_ = 0.0
        loss = 0.0
        for xi, yi in zip(X, y):
            p = _sigmoid(b + sum(wj * xj for wj, xj in zip(w, xi)))
            p = min(max(p, 1e-12), 1 - 1e-12)
            loss += -(yi * math.log(p) + (1 - yi) * math.log(1 - p))
            g = p - yi
            for j in range(d):
                dw[j] += g * xi[j]
            db_ += g
        for j in range(d):
            w[j] -= lr * dw[j] / n
        b -= lr * db_ / n
    loss /= n

    model_path.write_text(
        json.dumps({"cols": cols, "stats": stats, "w": w, "b": b}, indent=2)
    )

    scores = [_sigmoid(b + sum(wj * xj for wj, xj in zip(w, xi))) for xi in X]
    return {
        "n_train": n,
        "train_logloss": round(loss, 4),
        "train_auc": round(_auc(y, scores), 4),
        "train_accuracy": round(_accuracy(y, scores), 4),
    }


# ----------------------------------------------------------------------------
# stage 4: evaluation -- re-splits identically, scores the held-out rows
# ----------------------------------------------------------------------------
def evaluate_model(features_path, model_path, metrics_path, split_seed, holdout_frac):
    rows = json.loads(features_path.read_text())
    model = json.loads(model_path.read_text())
    _, holdout = _split(rows, split_seed, holdout_frac)

    cols, stats, w, b = model["cols"], model["stats"], model["w"], model["b"]
    X, y = _matrix(holdout, cols, stats)
    scores = [_sigmoid(b + sum(wj * xj for wj, xj in zip(w, xi))) for xi in X]
    preds = [1 if s >= 0.5 else 0 for s in scores]

    tp = sum(1 for p, t in zip(preds, y) if p == 1 and t == 1)
    fp = sum(1 for p, t in zip(preds, y) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, y) if p == 0 and t == 1)
    tn = sum(1 for p, t in zip(preds, y) if p == 0 and t == 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    metrics = {
        "n_holdout": len(holdout),
        "holdout_auc": round(_auc(y, scores), 4),
        "holdout_accuracy": round(_accuracy(y, scores), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }
    metrics_path.write_text(json.dumps(metrics, indent=2))
    return metrics


# ----------------------------------------------------------------------------
# reading back: walk the link graph outward from a starting experiment
# ----------------------------------------------------------------------------
def walk_chain(db, start):
    """Breadth-first walk over db.links(), i.e. the whole connected component.

    dexpter only hands you direct neighbours; reconstructing a multi-stage
    pipeline like this is a few lines on top.
    """
    seen = {start}
    order = [start]
    frontier = [start]
    while frontier:
        nxt = []
        for node in frontier:
            for neighbour in db.links(node):
                if neighbour not in seen:
                    seen.add(neighbour)
                    order.append(neighbour)
                    nxt.append(neighbour)
        frontier = nxt
    return order


def main():
    workdir = Path(tempfile.mkdtemp(prefix="dexpter_demo_"))
    print(f"working directory: {workdir}\n")

    db_path = workdir / "pipeline.dexpter"
    raw_path = workdir / "raw.json"
    feat_path = workdir / "features.json"
    model_path = workdir / "model.json"
    metrics_path = workdir / "metrics.json"

    # every experiment in this database must carry these two fields
    db = Dexpter.init(db_path, required_fields=["stage", "description"])

    SEED = 7
    SPLIT_SEED = 100
    HOLDOUT_FRAC = 0.25
    LR, EPOCHS = 0.3, 400

    # -- stage 1: simulate ---------------------------------------------------
    s1 = simulate_data(raw_path, n_rows=1500, seed=SEED)
    db.log(
        "data_sim",
        stage="simulate",
        description="synthetic customer-churn dataset",
        seed=SEED,
        raw_path=str(raw_path),
        **s1,
    )
    print(f"[data_sim]  {s1['n_rows']} rows, positive_rate={s1['positive_rate']}")

    # -- stage 2: features -------------------------------------------------
    s2 = engineer_features(raw_path, feat_path)
    db.log(
        "feat_eng",
        stage="features",
        description="ratio / interaction features derived from raw columns",
        source_path=str(raw_path),
        features_path=str(feat_path),
        links=["data_sim"],  # this feature set was built from that simulation
        **s2,
    )
    print(f"[feat_eng]  {s2['n_features']} features: {', '.join(s2['feature_cols'])}")

    # -- stage 3: train ----------------------------------------------------
    # log once up front with the config and status=running...
    db.log(
        "training",
        stage="train",
        description="full-batch logistic regression (pure python)",
        model="logistic_regression",
        lr=LR,
        epochs=EPOCHS,
        split_seed=SPLIT_SEED,
        holdout_frac=HOLDOUT_FRAC,
        status="running",
        links=["feat_eng"],
    )
    t0 = time.perf_counter()
    train_metrics = train_model(feat_path, model_path, LR, EPOCHS, SPLIT_SEED, HOLDOUT_FRAC)
    # ...then log the same id again to update it in place: fields merge, the
    # link to feat_eng and the original created_at are preserved.
    db.log(
        "training",
        status="done",
        wall_seconds=round(time.perf_counter() - t0, 3),
        model_path=str(model_path),
        **train_metrics,
    )
    print(
        f"[training]  train_auc={train_metrics['train_auc']} "
        f"logloss={train_metrics['train_logloss']}"
    )

    # -- stage 4: evaluate --------------------------------------------------
    s4 = evaluate_model(feat_path, model_path, metrics_path, SPLIT_SEED, HOLDOUT_FRAC)
    db.log(
        "eval",
        stage="evaluate",
        description="held-out metrics for the trained model",
        model_path=str(model_path),
        metrics_path=str(metrics_path),
        links=["training"],
        **s4,
    )
    print(
        f"[eval]      holdout_auc={s4['holdout_auc']} "
        f"accuracy={s4['holdout_accuracy']} f1={s4['f1']}"
    )

    # -- read it back ------------------------------------------------------
    print("\n" + "=" * 70)
    print("pipeline reconstructed from disk, walked backward from 'eval' via db.links()")
    print("=" * 70)

    fresh = Dexpter.load(db_path)
    for exp_id in walk_chain(fresh, "eval"):
        rec = fresh.get(exp_id)
        print(f"\n- {exp_id}  (stage={rec['stage']})")
        print(f"    {rec['description']}")
        print(f"    links  -> {', '.join(fresh.links(exp_id)) or '(none)'}")
        print(f"    logged {rec['created_at']}")
        if rec["updated_at"] != rec["created_at"]:
            print(f"    updated {rec['updated_at']}")

    # links are symmetric: we only ever linked *from* feat_eng and training,
    # but the upstream stages see those links too.
    print(f"\ndata_sim's links: {fresh.links('data_sim')}  (never linked explicitly from here)")
    print(f"total experiments: {len(fresh)}")

    print("\ninspect it yourself:")
    print(f"  dexpter list  {db_path}")
    print(f"  dexpter show  {db_path} training")
    print(f"  dexpter links {db_path} eval")


if __name__ == "__main__":
    main()
