import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dexpter import Dexpter, DexpterError  # noqa: E402


class ValidationTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "db.dexpter")
        db = Dexpter.init(self.path, required_fields=["stage"])
        db.log("a", stage="sim", acc=0.9)
        db.log("b", stage="train", links=["a"])

    def read(self):
        return json.loads(Path(self.path).read_text())

    def write(self, data):
        Path(self.path).write_text(json.dumps(data, indent=2))

    def edit(self, mutate):
        data = self.read()
        mutate(data)
        self.write(data)

    def report(self):
        return Dexpter.validate(self.path)

    # -- clean / benign ----------------------------------------------------

    def test_clean_file(self):
        r = self.report()
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual(r["seal"], "unsealed")

    def test_value_edit_is_not_flagged(self):
        self.edit(lambda d: d["a"].update(acc=0.95))
        r = self.report()
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warnings"], [])

    # -- hard errors -----------------------------------------------------

    def test_missing_file_raises(self):
        with self.assertRaises(DexpterError):
            Dexpter.validate(os.path.join(self.path, "nope"))

    def test_invalid_json(self):
        Path(self.path).write_text("{ not json")
        r = self.report()
        self.assertTrue(r["errors"])
        self.assertEqual(r["seal"], "unknown")

    def test_top_level_not_object(self):
        Path(self.path).write_text("[]")
        self.assertIn("top-level value is not a JSON object", self.report()["errors"])

    def test_meta_not_object(self):
        self.edit(lambda d: d.__setitem__("__dexpter__", "x"))
        self.assertTrue(any("not an object" in e for e in self.report()["errors"]))

    def test_required_fields_not_list_of_strings(self):
        self.edit(lambda d: d["__dexpter__"].__setitem__("required_fields", [1, 2]))
        self.assertTrue(any("required_fields" in e for e in self.report()["errors"]))

    def test_links_not_list(self):
        self.edit(lambda d: d["__dexpter__"].__setitem__("links", "nope"))
        self.assertIn("'links' is not a list", self.report()["errors"])

    def test_malformed_link_entry(self):
        self.edit(lambda d: d["__dexpter__"].__setitem__("links", [["a", "b", "c"]]))
        self.assertTrue(any("links[0]" in e for e in self.report()["errors"]))

    def test_content_hash_not_string(self):
        self.edit(lambda d: d["__dexpter__"].__setitem__("content_hash", 123))
        self.assertIn("'content_hash' is not a string", self.report()["errors"])

    def test_record_not_object(self):
        self.edit(lambda d: d.__setitem__("a", "oops"))
        self.assertIn("experiment 'a' is not an object", self.report()["errors"])

    def test_id_mismatch(self):
        self.edit(lambda d: d["a"].update(id="wrong"))
        self.assertTrue(any("mismatched 'id'" in e for e in self.report()["errors"]))

    # -- soft warnings -------------------------------------------------

    def test_missing_id_is_warning(self):
        self.edit(lambda d: d["a"].pop("id"))
        r = self.report()
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("missing 'id'" in w for w in r["warnings"]))

    def test_unparseable_timestamp(self):
        self.edit(lambda d: d["a"].update(created_at="yesterday"))
        self.assertTrue(any("unparseable 'created_at'" in w for w in self.report()["warnings"]))

    def test_updated_before_created(self):
        self.edit(lambda d: d["a"].update(created_at="2030-01-01T00:00:00+00:00"))
        self.assertTrue(
            any("'updated_at' before 'created_at'" in w for w in self.report()["warnings"])
        )

    def test_orphan_link_is_warning(self):
        self.edit(lambda d: d.pop("a"))
        r = self.report()
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("unknown experiment 'a'" in w for w in r["warnings"]))

    def test_missing_required_field_is_warning(self):
        self.edit(lambda d: d["a"].pop("stage"))
        self.assertTrue(
            any("missing required field" in w for w in self.report()["warnings"])
        )

    # -- load() interaction ------------------------------------------------

    def test_load_refuses_structural_errors(self):
        self.edit(lambda d: d.__setitem__("a", "oops"))
        with self.assertRaises(DexpterError):
            Dexpter.load(self.path)

    def test_load_validate_false_bypasses(self):
        self.edit(lambda d: d.__setitem__("a", "oops"))
        db = Dexpter.load(self.path, validate=False)
        self.assertIn("b", db)

    def test_load_allows_warnings(self):
        self.edit(lambda d: d["a"].pop("stage"))
        db = Dexpter.load(self.path)  # warnings don't block
        self.assertIn("a", db)

    # -- seal states via validate --------------------------------------

    def test_seal_ok_and_mismatch(self):
        db = Dexpter.load(self.path)
        db.seal()
        self.assertEqual(self.report()["seal"], "ok")
        self.edit(lambda d: d["a"].update(acc=0.1))
        self.assertEqual(self.report()["seal"], "mismatch")

    def test_sealed_without_hash(self):
        self.edit(lambda d: d["__dexpter__"].__setitem__("sealed", True))
        r = self.report()
        self.assertEqual(r["seal"], "unknown")
        self.assertTrue(any("no content_hash" in w for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main()
