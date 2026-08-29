# Changelog

All notable changes to dexpter are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and dexpter follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-08-28

Initial release.

### Added

- **Core store** (`Dexpter`) — a JSON file where each top-level key is an
  experiment id and each value is a free-form record.
  - `Dexpter.init()` / `Dexpter.load()` / `db.log()` / `db.get()` /
    `db.delete()`.
  - `log()` upserts: logging an existing id merges fields, bumps
    `updated_at`, and preserves `created_at`.
  - Auto-managed `id` / `created_at` / `updated_at`; setting them through
    `log()` raises `DexpterError`.
  - Optional `required_fields`, enforced on `log()`, changeable later with
    `set_required_fields()` (which reports which existing records fall
    short).
  - Container protocol: `len(db)`, `iter(db)`, `x in db`, `db.experiments`.
  - Atomic writes (temp file + rename) so a crash mid-write can't corrupt
    the database.
- **Linking** — symmetric, unlabeled edges between experiments, stored in
  the `__dexpter__` metadata block rather than on the records.
  - `db.link()` / `db.unlink()` / `db.links()`, plus a `links=` keyword on
    `log()`.
  - Both endpoints must exist; self-links are rejected; edges are sorted and
    deduplicated on disk; `delete()` prunes edges that reference the removed
    experiment.
- **Integrity**
  - `Dexpter.validate()` / `dexpter check` — structural report of `errors`
    (shape the API can't work with) and `warnings` (usable but an invariant
    was lost). `load()` refuses a file with errors unless `validate=False`.
  - Opt-in sealing (`Dexpter.init(sealed=True)`, `db.seal()` / `db.unseal()`
    / `db.verify_seal()`) — stores a canonical content hash and warns
    (`DexpterSealWarning`) on `load()` if the file changed outside dexpter.
    Reformatting does not trip it; changed values do.
- **CLI** (`dexpter`) — `init` (`--require`, `--seal`), `list`, `show`,
  `require`, `link`, `unlink`, `links`, `check`, `seal`, `unseal`.
- **Examples** — `examples/pipeline_demo.py` (four-stage churn pipeline,
  pure standard library) and `examples/integrity_demo.py` (structural check
  and sealing walkthrough).
- **Recipes** (`examples/recipes/`) — copy-and-adapt templates for patterns
  intentionally left out of the core: field history, experiment diffing,
  tagging, transitive link traversal, pipeline reconstruction.
- **Tests** — standard-library `unittest` suite, no test dependencies
  (`python -m unittest discover`).
- `dexpter.__version__`.

[Unreleased]: https://github.com/rjapplin/dexpter/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rjapplin/dexpter/releases/tag/v1.0.0
