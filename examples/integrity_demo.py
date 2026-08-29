"""Demo: catching edits made outside the API.

dexpter files are meant to be readable and hand-editable -- but a careless
editor save can still break one. This walks through the two guards:

  1. structural check  -- Dexpter.validate() / `dexpter check`
  2. sealing            -- opt-in content hash, warns on ANY outside change

Pure standard library. Nothing here is a dependency of dexpter itself.

    python examples/integrity_demo.py
"""

import json
import sys
import tempfile
import warnings
from pathlib import Path

try:
    from dexpter import Dexpter, DexpterError
except ImportError:  # running straight from a checkout without `pip install`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dexpter import Dexpter, DexpterError


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def hand_edit(path, mutate):
    """Simulate someone opening the file in a text editor and saving."""
    raw = json.loads(path.read_text())
    mutate(raw)
    path.write_text(json.dumps(raw, indent=2))


def show_report(path):
    report = Dexpter.validate(path)
    print(f"  validate() -> seal={report['seal']!r}")
    for msg in report["errors"]:
        print(f"    error:   {msg}")
    for msg in report["warnings"]:
        print(f"    warning: {msg}")
    if not report["errors"] and not report["warnings"]:
        print("    (no structural problems)")
    return report


def main():
    workdir = Path(tempfile.mkdtemp(prefix="dexpter_integrity_"))

    # ----------------------------------------------------------- part 1
    banner("1. structural check")

    path = workdir / "runs.dexpter"
    db = Dexpter.init(path, required_fields=["stage"])
    db.log("sim", stage="simulate", rows=1500)
    db.log("feat", stage="features", n_features=6, links=["sim"])
    db.log("train", stage="train", auc=0.87, links=["feat"])
    print(f"file: {path}")

    print("\nfresh from the API:")
    show_report(path)

    print("\nafter a legit hand-edit (fix a value):")
    hand_edit(path, lambda r: r["train"].update(auc=0.91))
    show_report(path)
    print("  -> a changed value is not flagged; editing the file is allowed")

    print("\nafter a careless edit (delete 'feat' but leave its links):")
    hand_edit(path, lambda r: r.pop("feat"))
    show_report(path)
    db2 = Dexpter.load(path)
    print(f"  Dexpter.load() still works ({len(db2)} experiments); warnings only")

    print("\nafter structural damage (a record becomes a string):")
    hand_edit(path, lambda r: r.__setitem__("sim", "oops"))
    show_report(path)
    try:
        Dexpter.load(path)
    except DexpterError as e:
        print(f"  Dexpter.load() refused: {str(e)[:88]}...")
    salvage = Dexpter.load(path, validate=False)
    print(f"  Dexpter.load(validate=False) works for salvage: {sorted(salvage)}")

    # ----------------------------------------------------------- part 2
    banner("2. sealing (opt-in tamper-evidence)")

    sealed_path = workdir / "sealed.dexpter"
    sdb = Dexpter.init(sealed_path, sealed=True)  # or call sdb.seal() any time
    sdb.log("run1", lr=0.01)
    sdb.log("run1", accuracy=0.93)
    print(f"file: {sealed_path}")
    print(f"  db.sealed={sdb.sealed}  db.verify_seal()={sdb.verify_seal()}")

    print("\nload it untouched:")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Dexpter.load(sealed_path)
    print(f"  warnings: {[w.category.__name__ for w in caught] or 'none'}")

    print("\nhand-edit one value, then load again:")
    hand_edit(sealed_path, lambda r: r["run1"].update(accuracy=0.99))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reopened = Dexpter.load(sealed_path)
    for w in caught:
        print(f"  {w.category.__name__}: {w.message}")
    print(f"  db.verify_seal() = {reopened.verify_seal()}")
    print(f"  validate() seal  = {Dexpter.validate(sealed_path)['seal']!r}")

    print("\naccept the edit by re-sealing:")
    reopened.seal()
    print(f"  validate() seal = {Dexpter.validate(sealed_path)['seal']!r}")

    print("\nreformat only -- indent + key order, same data:")
    raw = json.loads(sealed_path.read_text())
    sealed_path.write_text(json.dumps(raw, indent=4, sort_keys=True))
    print(f"  validate() seal = {Dexpter.validate(sealed_path)['seal']!r}  (canonical hash ignores formatting)")

    print("\nturn sealing back off:")
    Dexpter.load(sealed_path).unseal()
    print(f"  validate() seal = {Dexpter.validate(sealed_path)['seal']!r}")

    print(f"\nfiles left in {workdir}")


if __name__ == "__main__":
    main()
