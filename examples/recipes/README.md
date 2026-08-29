# Recipes

Patterns you can layer on top of dexpter without them being core features.
Each file is a self-contained template with a runnable demo — copy it into
your project and adapt.

| File | Pattern |
|------|---------|
| `field_history.py` | Record when each field first appeared on an experiment |
| `experiment_diff.py` | Diff two experiment records, `git diff` style |
| `tagging.py` | Tag experiments and query by tag |
| `pipeline_reconstruction.py` | Rebuild a linked pipeline and put it in run order |

```bash
python examples/recipes/experiment_diff.py
```

These deliberately live outside the `dexpter` package: they're all a handful
of lines against the public API (`log`, `get`, `experiments`, `links`), which
is the point — the core stays small and unopinionated, and you compose what
your project needs.
