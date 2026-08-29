import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dexpter import Dexpter, DexpterError  # noqa: E402


class LinkingTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "db.dexpter")
        self.db = Dexpter.init(self.path)
        self.db.log("a", x=1)
        self.db.log("b", x=2)
        self.db.log("c", x=3)

    def raw_links(self):
        return json.loads(Path(self.path).read_text())["__dexpter__"]["links"]

    def test_link_is_symmetric(self):
        self.db.link("a", "b")
        self.assertEqual(self.db.links("a"), ["b"])
        self.assertEqual(self.db.links("b"), ["a"])

    def test_link_is_idempotent_and_normalized(self):
        self.db.link("b", "a")
        self.db.link("a", "b")
        self.assertEqual(self.raw_links(), [["a", "b"]])

    def test_links_sorted_and_deduped_on_disk(self):
        self.db.link("c", "a")
        self.db.link("a", "b")
        self.assertEqual(self.raw_links(), [["a", "b"], ["a", "c"]])

    def test_self_link_rejected(self):
        with self.assertRaises(DexpterError):
            self.db.link("a", "a")

    def test_link_to_unknown_rejected(self):
        with self.assertRaises(DexpterError):
            self.db.link("a", "ghost")

    def test_unlink(self):
        self.db.link("a", "b")
        self.db.unlink("a", "b")
        self.assertEqual(self.db.links("a"), [])
        self.db.unlink("a", "b")  # no error the second time

    def test_links_returns_sorted_unique(self):
        self.db.link("a", "b")
        self.db.link("a", "c")
        self.assertEqual(self.db.links("a"), ["b", "c"])

    def test_links_unknown_experiment_is_empty(self):
        self.assertEqual(self.db.links("nope"), [])

    def test_log_links_kwarg_additive(self):
        self.db.log("a", links=["b"])
        self.db.log("a", links=["c"])
        self.assertEqual(self.db.links("a"), ["b", "c"])

    def test_log_links_accepts_string(self):
        self.db.log("a", links="b")
        self.assertEqual(self.db.links("a"), ["b"])

    def test_log_links_validated_before_write(self):
        with self.assertRaises(DexpterError):
            self.db.log("new_exp", value=1, links=["ghost"])
        self.assertNotIn("new_exp", self.db)

    def test_log_self_link_rejected(self):
        with self.assertRaises(DexpterError):
            self.db.log("a", links=["a"])

    def test_delete_prunes_edges(self):
        self.db.link("a", "b")
        self.db.link("b", "c")
        self.db.delete("b")
        self.assertEqual(self.raw_links(), [])
        self.assertEqual(self.db.links("a"), [])
        self.assertEqual(self.db.links("c"), [])

    def test_links_survive_reload(self):
        self.db.link("a", "b")
        reopened = Dexpter.load(self.path)
        self.assertEqual(reopened.links("a"), ["b"])


if __name__ == "__main__":
    unittest.main()
