import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dexpter import Dexpter, DexpterSealWarning  # noqa: E402


class SealingTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "db.dexpter")

    def read(self):
        return json.loads(Path(self.path).read_text())

    def write(self, data):
        Path(self.path).write_text(json.dumps(data, indent=2))

    def tamper(self, mutate):
        data = self.read()
        mutate(data)
        self.write(data)

    def test_init_sealed_stores_hash(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        self.assertTrue(db.sealed)
        meta = self.read()["__dexpter__"]
        self.assertIs(meta["sealed"], True)
        self.assertIsInstance(meta["content_hash"], str)

    def test_unsealed_has_no_hash(self):
        db = Dexpter.init(self.path)
        db.log("a", x=1)
        self.assertNotIn("content_hash", self.read()["__dexpter__"])
        self.assertIsNone(db.verify_seal())

    def test_verify_seal_true_when_clean(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        self.assertTrue(db.verify_seal())

    def test_seal_can_be_turned_on_later(self):
        db = Dexpter.init(self.path)
        db.log("a", x=1)
        db.seal()
        self.assertTrue(db.sealed)
        self.assertTrue(db.verify_seal())

    def test_load_untouched_sealed_file_does_not_warn(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Dexpter.load(self.path)
        self.assertEqual(caught, [])

    def test_load_warns_after_external_edit(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        self.tamper(lambda d: d["a"].update(x=999))
        with self.assertWarns(DexpterSealWarning):
            reopened = Dexpter.load(self.path)
        self.assertFalse(reopened.verify_seal())

    def test_reseal_accepts_edits(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        self.tamper(lambda d: d["a"].update(x=999))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reopened = Dexpter.load(self.path)
        reopened.seal()
        self.assertTrue(reopened.verify_seal())
        self.assertEqual(Dexpter.validate(self.path)["seal"], "ok")

    def test_reformatting_does_not_trip_seal(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        data = self.read()
        Path(self.path).write_text(json.dumps(data, indent=4, sort_keys=True))
        self.assertEqual(Dexpter.validate(self.path)["seal"], "ok")

    def test_unseal_removes_hash_and_flag(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        db.unseal()
        meta = self.read()["__dexpter__"]
        self.assertNotIn("content_hash", meta)
        self.assertNotIn("sealed", meta)
        self.assertIsNone(db.verify_seal())

    def test_unsealed_file_load_never_warns_even_if_edited(self):
        db = Dexpter.init(self.path)
        db.log("a", x=1)
        self.tamper(lambda d: d["a"].update(x=999))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Dexpter.load(self.path)
        self.assertEqual(caught, [])

    def test_sealed_state_persists_across_load(self):
        db = Dexpter.init(self.path, sealed=True)
        db.log("a", x=1)
        reopened = Dexpter.load(self.path)
        self.assertTrue(reopened.sealed)
        reopened.log("b", y=2)
        self.assertTrue(reopened.verify_seal())


if __name__ == "__main__":
    unittest.main()
