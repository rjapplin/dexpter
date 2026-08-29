# dexpter

**d**ata science **exp**eriment **t**rack**er** — a lightweight, flexible
JSON-backed experiment tracker for data science work.

No server, no database, no dependencies beyond the Python standard library.
A dexpter "database" is a single JSON file. Each top-level key is one
experiment id; each value is that experiment's record, made of whatever
arbitrary fields you choose to log.

## Install

From the dexpter project directory (this repo):

```bash
pip install -e /path/to/dexpter
```

Use `-e` (editable) if dexpter's own source may still change and you want
that reflected immediately without reinstalling. Drop `-e` for a normal
pinned install. This works from any other project's venv — dexpter doesn't
need to be published anywhere; pip builds it from the local path.

Installing gives you both:
- the `dexpter` Python package (`from dexpter import Dexpter, DexpterError`)
- a `dexpter` CLI command

## Core concepts

- **Database file**: one JSON file = one body of work / project. Pick any
  path and extension you like (`experiments.json`, `runs.dexpter`, etc.) —
  the extension is cosmetic, the content is always plain JSON.
- **Experiment**: one entry in that file, identified by a string id you
  choose (e.g. `"resnet18_baseline"`). Logging the same id again updates
  that experiment in place rather than creating a duplicate.
- **Fields**: arbitrary keyword arguments you pass to `log()`. No schema
  beyond whatever required fields you've configured (see below).
- **Auto-managed fields**: every record automatically gets `id`,
  `created_at`, and `updated_at`. You cannot set these yourself — passing
  them to `log()` raises `DexpterError`.

## Python API

```python
from dexpter import Dexpter, DexpterError

# Create a new database (once)
db = Dexpter.init("experiments.json")

# Or require certain fields be present on every experiment
db = Dexpter.init("experiments.json", required_fields=["description"])

# Re-open an existing database later
db = Dexpter.load("experiments.json")

# Log a new experiment (creates it)
db.log(
    "resnet18_baseline",
    description="baseline run with default hyperparams",
    model="resnet18",
    lr=0.01,
)

# Log again with the same id to update it (merges fields, bumps updated_at,
# preserves created_at)
db.log("resnet18_baseline", accuracy=0.91, epochs_run=12)

# Read
db.get("resnet18_baseline")   # dict, or None if not found
db.experiments                 # dict of every experiment, keyed by id
list(db)                       # just the ids
len(db)                        # experiment count
"resnet18_baseline" in db      # membership check

# Delete (also removes any links touching this experiment)
db.delete("resnet18_baseline")

# Link related experiments (symmetric, unlabeled edges between ids)
db.link("training_run3", "feat_gen_v1")     # both ids must already exist; idempotent
db.link("training_run3", "target_gen_v1")
db.links("training_run3")                    # -> ["feat_gen_v1", "target_gen_v1"] (sorted)
db.unlink("training_run3", "feat_gen_v1")    # no error if that link wasn't there

# Or declare links right when you log (additive — unions with existing links)
db.log("training_run3", accuracy=0.91, links=["feat_gen_v1", "target_gen_v1"])

# Required fields can be changed later too
db.required_fields                          # current list
gaps = db.set_required_fields(["description", "owner"])
# gaps = {experiment_id: [missing_field, ...]} for any existing experiments
# that don't satisfy the new requirement yet (informational, not blocking —
# but the *next* log() call on one of those ids will enforce it)

# Check a file for damage from hand-editing outside the API
report = Dexpter.validate("experiments.json")
# {"errors": [...], "warnings": [...], "seal": "unsealed"}
```

`DexpterError` is raised for: missing required fields, attempting to set a
reserved field (`id`/`created_at`/`updated_at`), calling `init()` on a path
that already exists (pass `exist_ok=True` to reuse it instead),
`load()`/`delete()` on something that doesn't exist, linking to a
nonexistent experiment / linking an experiment to itself, or `load()`ing a
file with structural damage (see [Integrity](#integrity)).

## Linking experiments

A link is a **symmetric, unlabeled edge between two experiment ids**. There's
no notion of parent/child or upstream/downstream — dexpter just records that
two experiments are related and lets you look that up from either side.

Typical use: a feature-generation experiment, a target-generation experiment,
a training experiment, and an evaluation experiment that all belong to one
modeling effort. Link them and you can jump between them later:

```python
db.log("feat_gen_v1", rows=1_000_000, n_features=42)
db.log("target_gen_v1", label="churn_30d", positive_rate=0.08)
db.log("training_run3", model="xgboost", auc=0.87,
       links=["feat_gen_v1", "target_gen_v1"])
db.log("eval_run3", holdout_auc=0.85, links=["training_run3"])

db.links("training_run3")   # -> ['eval_run3', 'feat_gen_v1', 'target_gen_v1']
db.links("feat_gen_v1")     # -> ['training_run3']
```

Links are stored centrally in the `__dexpter__` metadata block, not on the
experiment records, so `db.get(...)` / `db.experiments` stay exactly as they
were. `db.links(id)` returns direct neighbours only (no transitive walk).
Deleting an experiment drops every link that referenced it.

## Integrity

Editing the JSON file by hand is fine and supported — but a careless editor
save can break it. Two levels of protection:

**Structural check** — `Dexpter.validate(path)` (or `dexpter check <path>`)
reports:

- `errors` — the file no longer matches dexpter's shape and the API may
  misbehave: not an object, a record that isn't an object, an `id` field
  that disagrees with its key, a malformed `links` list. `load()` refuses a
  file with errors unless you pass `validate=False`.
- `warnings` — still usable, but an invariant was lost: a missing/`unparseable`
  `created_at`/`updated_at`, `updated_at` before `created_at`, a link to an
  id that no longer exists, a record missing a required field.

Editing a *value* (say fixing `lr: 0.01` → `0.02`) is not flagged — that's a
supported edit.

**Sealing (opt-in tamper-evidence)** — off by default. When on, every write
stores a hash of the contents in `__dexpter__`, and `load()` warns
(`DexpterSealWarning`) if *anything* changed outside dexpter, including
deliberate value edits.

```python
db = Dexpter.init("experiments.json", sealed=True)   # or db.seal() any time
db.sealed            # True
db.verify_seal()     # True (matches) / False (changed) / None (not sealed)
db.seal()            # re-baseline: accept the current file as the new truth
db.unseal()          # turn it back off, drop the stored hash
```

The hash is computed over a canonical form, so reformatting the file (`jq`,
an IDE "format document", whitespace) doesn't trip it — only changed values
do. It's tamper-*evidence*, not protection: the hash lives in the same file
and anyone can recompute it.

## Example

[`examples/pipeline_demo.py`](examples/pipeline_demo.py) runs a four-stage
churn pipeline — simulate → feature-eng → train → evaluate — logging one
experiment per stage, linking each to the stage it consumed, then re-opening
the database and walking the links to reconstruct the pipeline. It's pure
standard library (a from-scratch logistic regression), so it adds no
dependency to dexpter itself:

```bash
python examples/pipeline_demo.py
```

[`examples/integrity_demo.py`](examples/integrity_demo.py) walks through the
structural check and sealing — a legit value edit passing, a careless edit
producing warnings, structural damage being refused by `load()`, and a
sealed file catching an out-of-band change.

[`examples/recipes/`](examples/recipes/) has small copy-and-adapt templates
for patterns you can layer on the public API — field history, experiment
diffing, tagging, transitive link traversal, pipeline reconstruction — none
of which need to be in the core.

## CLI

```bash
# Create a database, optionally with required fields
dexpter init experiments.json
dexpter init experiments.json --require description --require owner

# List all experiments (shows required fields + created/updated timestamps)
dexpter list experiments.json

# Show one experiment's full record as pretty JSON
dexpter show experiments.json resnet18_baseline

# View or change required fields on an existing database
dexpter require experiments.json
dexpter require experiments.json --add owner
dexpter require experiments.json --remove owner

# Link / unlink experiments, or list one experiment's links
dexpter link experiments.json training_run3 feat_gen_v1
dexpter unlink experiments.json training_run3 feat_gen_v1
dexpter links experiments.json training_run3

# Check the file for structural damage / tampering (exit 1 on errors)
dexpter check experiments.json

# Tamper-evidence (also: dexpter init --seal)
dexpter seal experiments.json
dexpter unseal experiments.json
```

The CLI is read/inspect + schema/link management only — logging experiment
data is done through the Python API (`db.log(...)`), since that's where the
actual metrics/params/results come from. `list` shows a `links=N` column for
experiments that have links; `show` prints a `links:` line (on stderr, so
`show ... | jq` still gets clean JSON).

## File format

The JSON file is just a plain object. A reserved `__dexpter__` top-level key
holds metadata (`required_fields`, `links`, and — only when sealing is on —
`sealed` / `content_hash`) and is hidden from `db.experiments`, `len(db)`,
`in`, and iteration — you'll never see it unless you open the raw file
yourself. Each entry in `links` is a `[id_a, id_b]` pair, stored sorted and
deduplicated, so the file stays stable across diffs.

```json
{
  "__dexpter__": {
    "required_fields": ["description"],
    "links": [
      ["feat_gen_v1", "training_run3"],
      ["target_gen_v1", "training_run3"]
    ]
  },
  "resnet18_baseline": {
    "description": "baseline run with default hyperparams",
    "model": "resnet18",
    "lr": 0.01,
    "accuracy": 0.91,
    "epochs_run": 12,
    "id": "resnet18_baseline",
    "created_at": "2026-08-28T19:16:29.451799+00:00",
    "updated_at": "2026-08-28T19:22:13.159574+00:00"
  }
}
```

Writes are atomic (write to a temp file, then rename over the target), so
a crash mid-write won't corrupt the database.

## What this is not

dexpter deliberately has no server, no UI, no artifact/model storage, no
metric time-series (each `log()` call is a full-record snapshot, not an
appended data point), and no multi-user concurrency story. If you need any
of that, reach for something like MLflow instead. dexpter is for the "just
let me log arbitrary stuff about a run in a file I can read/diff/edit
myself" use case.

## Development

Tests are standard-library `unittest` — no test dependencies:

```bash
python -m unittest discover
```
