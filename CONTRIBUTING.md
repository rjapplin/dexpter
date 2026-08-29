# Contributing

Thanks for taking a look. dexpter is intentionally small, so a quick note on
what fits.

## Scope

The core stays minimal and unopinionated: it owns correctness guarantees you
can't get from outside it — atomic writes, an immutable `created_at`, link
integrity, structural validation — and little else. If something can be built
on top of the public API and get it exactly right, it belongs in
`examples/recipes/`, not the core.

Please open an issue before starting a feature PR so we can agree on whether
it's a core change or a recipe.

## Ground rules

- **No runtime dependencies.** Standard library only — this is a feature, not
  a limitation.
- **Tests are standard-library `unittest`**, no test dependencies:
  ```bash
  python -m unittest discover
  ```
  Add tests for any behaviour change. CI runs them on Python 3.9–3.13.
- **Match the surrounding style** — plain functions, short docstrings, no
  type hints in the core today.
- Keep the JSON file format stable and diff-friendly. A format change needs a
  migration story and a `CHANGELOG` entry.

## Releasing

1. Bump the version in **both** `pyproject.toml` and
   `src/dexpter/__init__.py`.
2. Move the `[Unreleased]` notes in `CHANGELOG.md` into a dated version
   section.
3. Commit, then tag `vX.Y.Z` and push the tag.
