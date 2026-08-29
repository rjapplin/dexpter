import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dexpter import Dexpter, DexpterError  # noqa: E402
from dexpter import core  # noqa: E402


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def path(self, name="db.dexpter"):
        return os.path.join(self.tmp, name)


class InitLoad(CoreTestCase):
    def test_init_creates_file_with_metadata(self):
        db = Dexpter.init(self.path())
        self.assertTrue(Path(self.path()).exists())
        raw = json.loads(Path(self.path()).read_text())
        self.assertEqual(raw["__dexpter__"], {"required_fields": [], "links": []})
        self.assertEqual(len(db), 0)
        self.assertEqual(list(db), [])

    def test_init_rejects_existing_path(self):
        Dexpter.init(self.path())
        with self.assertRaises(DexpterError):
            Dexpter.init(self.path())

    def test_init_exist_ok_reuses(self):
        db = Dexpter.init(self.path())
        db.log("a", x=1)
        again = Dexpter.init(self.path(), exist_ok=True)
        self.assertIn("a", again)

    def test_init_rejects_reserved_required_field(self):
        with self.assertRaises(DexpterError):
            Dexpter.init(self.path(), required_fields=["id"])

    def test_load_missing_file(self):
        with self.assertRaises(DexpterError):
            Dexpter.load(self.path("nope.dexpter"))

    def test_load_backfills_legacy_metadata(self):
        Path(self.path()).write_text(json.dumps({"x": {"id": "x"}}))
        db = Dexpter.load(self.path())
        self.assertEqual(db.links("x"), [])
        self.assertEqual(db.required_fields, [])

    def test_load_tolerates_corrupt_metadata_when_not_validating(self):
        Path(self.path()).write_text(json.dumps({"__dexpter__": "broken", "x": {"id": "x"}}))
        db = Dexpter.load(self.path(), validate=False)
        self.assertEqual(db.required_fields, [])


class Logging(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.db = Dexpter.init(self.path())

    def test_log_creates_and_returns_record(self):
        rec = self.db.log("a", model="resnet", lr=0.1)
        self.assertEqual(rec["id"], "a")
        self.assertIn("created_at", rec)
        self.assertIn("updated_at", rec)
        self.assertEqual(rec["model"], "resnet")

    def test_log_update_merges_and_preserves_created_at(self):
        r1 = self.db.log("a", x=1)
        time.sleep(0.01)
        r2 = self.db.log("a", y=2)
        self.assertEqual(r2["created_at"], r1["created_at"])
        self.assertGreater(r2["updated_at"], r1["updated_at"])
        self.assertEqual(
            self.db.get("a"),
            {
                "x": 1,
                "y": 2,
                "id": "a",
                "created_at": r1["created_at"],
                "updated_at": r2["updated_at"],
            },
        )

    def test_reserved_fields_rejected(self):
        for field in ("id", "created_at", "updated_at"):
            with self.assertRaises(DexpterError):
                self.db.log("a", **{field: "x"})

    def test_meta_key_is_reserved_id(self):
        with self.assertRaises(DexpterError):
            self.db.log("__dexpter__", x=1)

    def test_get_returns_copy(self):
        self.db.log("a", x=1)
        rec = self.db.get("a")
        rec["x"] = 999
        self.assertEqual(self.db.get("a")["x"], 1)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.db.get("missing"))

    def test_experiments_excludes_meta_and_copies(self):
        self.db.log("a", x=1)
        exps = self.db.experiments
        self.assertEqual(set(exps), {"a"})
        exps["a"]["x"] = 999
        self.assertEqual(self.db.get("a")["x"], 1)

    def test_container_protocol(self):
        self.db.log("a", x=1)
        self.db.log("b", x=2)
        self.assertEqual(len(self.db), 2)
        self.assertIn("a", self.db)
        self.assertNotIn("__dexpter__", self.db)
        self.assertEqual(sorted(self.db), ["a", "b"])

    def test_delete(self):
        self.db.log("a", x=1)
        self.db.delete("a")
        self.assertNotIn("a", self.db)
        with self.assertRaises(DexpterError):
            self.db.delete("a")

    def test_delete_rejects_meta_key(self):
        with self.assertRaises(DexpterError):
            self.db.delete("__dexpter__")
        self.assertIn("__dexpter__", json.loads(Path(self.path()).read_text()))


class RequiredFields(CoreTestCase):
    def test_enforced_on_log(self):
        db = Dexpter.init(self.path(), required_fields=["description"])
        with self.assertRaises(DexpterError):
            db.log("a", x=1)
        db.log("a", description="ok")
        self.assertIn("a", db)

    def test_set_required_fields_reports_gaps(self):
        db = Dexpter.init(self.path())
        db.log("a", x=1)
        db.log("b", owner="me")
        gaps = db.set_required_fields(["owner"])
        self.assertEqual(gaps, {"a": ["owner"]})
        self.assertEqual(db.required_fields, ["owner"])

    def test_set_required_fields_rejects_reserved(self):
        db = Dexpter.init(self.path())
        with self.assertRaises(DexpterError):
            db.set_required_fields(["created_at"])


class AtomicWrite(CoreTestCase):
    def test_failed_save_leaves_file_intact_and_no_tmp(self):
        db = Dexpter.init(self.path())
        db.log("a", x=1)
        before = Path(self.path()).read_text()

        original = core.json.dump
        core.json.dump = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
        try:
            with self.assertRaises(RuntimeError):
                db.log("b", y=2)
        finally:
            core.json.dump = original

        self.assertEqual(Path(self.path()).read_text(), before)
        leftovers = [p for p in os.listdir(self.tmp) if p.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
