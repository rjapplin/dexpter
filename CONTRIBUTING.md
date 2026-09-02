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

## Submitting a change

1. **Open an issue first** (see [Scope](#scope)) so we can agree the change
   is a good fit before you put time into it.
2. **Fork** the repo on GitHub and clone your fork locally.
3. **Create a feature branch** off `main` — e.g.
   `git checkout -b short-description`. Don't commit to `main` directly; it
   makes the PR and any later rebase cleaner.
4. **Make the change, and add or update tests** so the new behaviour is
   covered. Before pushing, run the suite and the examples and make sure both
   are clean:
   ```bash
   python -m unittest discover
   for f in examples/*.py examples/recipes/*.py; do python "$f"; done
   ```
5. **Add a line to `CHANGELOG.md`** under the `## [Unreleased]` heading, in
   the right group (`Added` / `Changed` / `Fixed` / `Removed`). Leave the
   version numbers in `pyproject.toml` and `src/dexpter/__init__.py` alone —
   I set the version at release time.
6. **Push** the branch to your fork.
7. **Open a pull request** against `main`. Say what changed and why, and link
   the issue from step 1. One focused change per PR.
8. **Review.** I'll get to it when I have time — this is a side project, so a
   slow response isn't a reflection on the PR. I may ask for changes; push
   more commits to the same branch and the PR updates automatically.
9. Once it's approved and merged, you're done. I handle the tag and the PyPI
   release; your change ships with the next version.

## Releasing

Maintainer only — contributors just add to `## [Unreleased]` (above) and
stop there.

1. Bump the version in **both** `pyproject.toml` and
   `src/dexpter/__init__.py` (pick patch / minor / major per
   [SemVer](https://semver.org)).
2. Rename the `## [Unreleased]` section in `CHANGELOG.md` to
   `## [X.Y.Z] - <date>`, add a fresh empty `## [Unreleased]` above it, and
   update the link references at the bottom of the file.
3. Commit (`dexpter X.Y.Z`) and push to `main`.
4. Draft a GitHub release: new tag `vX.Y.Z` targeting `main`, paste the new
   CHANGELOG section as the body, publish.
5. Publishing fires `.github/workflows/publish.yml`. Approve the `pypi`
   deployment in the Actions tab; it builds and uploads to PyPI via Trusted
   Publishing.
6. Confirm `pip install dexpter` in a clean virtualenv pulls the new version.
