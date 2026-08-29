import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dexpter import Dexpter, cli  # noqa: E402


def run_cli(*args):
    """Invoke the CLI in-process. Returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "db.dexpter")
        saved = warnings.showwarning
        self.addCleanup(setattr, warnings, "showwarning", saved)


class InitAndInspect(CliTestCase):
    def test_init(self):
        code, out, _ = run_cli("init", self.path)
        self.assertEqual(code, 0)
        self.assertIn("Initialized", out)
        self.assertTrue(os.path.exists(self.path))

    def test_init_with_required_and_seal(self):
        code, out, _ = run_cli("init", self.path, "--require", "stage", "--seal")
        self.assertEqual(code, 0)
        self.assertIn("required fields: stage", out)
        self.assertIn("sealed: on", out)
        self.assertTrue(Dexpter.load(self.path).sealed)

    def test_init_existing_fails(self):
        run_cli("init", self.path)
        code, _, err = run_cli("init", self.path)
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_list_empty_and_populated(self):
        run_cli("init", self.path)
        code, out, _ = run_cli("list", self.path)
        self.assertIn("(no experiments logged)", out)

        db = Dexpter.load(self.path)
        db.log("a", x=1)
        db.log("b", x=2, links=["a"])
        code, out, _ = run_cli("list", self.path)
        self.assertEqual(code, 0)
        self.assertIn("a\t", out)
        self.assertIn("links=1", out)

    def test_show_emits_json_on_stdout_links_on_stderr(self):
        db = Dexpter.init(self.path)
        db.log("a", x=1)
        db.log("b", x=2, links=["a"])
        code, out, err = run_cli("show", self.path, "b")
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["id"], "b")
        self.assertIn("links: a", err)

    def test_show_missing_experiment(self):
        Dexpter.init(self.path)
        code, _, err = run_cli("show", self.path, "ghost")
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)


class RequireCommand(CliTestCase):
    def test_view_and_modify(self):
        db = Dexpter.init(self.path)
        db.log("a", x=1)

        code, out, _ = run_cli("require", self.path)
        self.assertIn("(none)", out)

        code, out, _ = run_cli("require", self.path, "--add", "owner")
        self.assertEqual(code, 0)
        self.assertIn("owner", out)
        self.assertIn("warning:", out)  # existing 'a' lacks it

        code, out, _ = run_cli("require", self.path, "--remove", "owner")
        self.assertIn("(none)", out)


class LinkCommands(CliTestCase):
    def setUp(self):
        super().setUp()
        db = Dexpter.init(self.path)
        db.log("a", x=1)
        db.log("b", x=2)

    def test_link_unlink_links(self):
        code, out, _ = run_cli("link", self.path, "a", "b")
        self.assertEqual(code, 0)
        self.assertIn("linked", out)

        code, out, _ = run_cli("links", self.path, "a")
        self.assertEqual(out.strip(), "b")

        run_cli("unlink", self.path, "a", "b")
        code, out, _ = run_cli("links", self.path, "a")
        self.assertIn("(no links)", out)

    def test_link_unknown_fails(self):
        code, _, err = run_cli("link", self.path, "a", "ghost")
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_links_unknown_experiment_fails(self):
        code, _, err = run_cli("links", self.path, "ghost")
        self.assertEqual(code, 1)


class CheckAndSeal(CliTestCase):
    def _populate(self, sealed=False):
        db = Dexpter.init(self.path, sealed=sealed)
        db.log("a", x=1)
        db.log("b", x=2, links=["a"])
        return db

    def test_check_clean(self):
        self._populate()
        code, out, _ = run_cli("check", self.path)
        self.assertEqual(code, 0)
        self.assertIn("ok: no problems found", out)

    def test_check_structural_error_exits_1(self):
        self._populate()
        data = json.load(open(self.path))
        data["a"] = "broken"
        open(self.path, "w").write(json.dumps(data))
        code, _, err = run_cli("check", self.path)
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_check_reports_seal_intact(self):
        self._populate(sealed=True)
        code, out, _ = run_cli("check", self.path)
        self.assertEqual(code, 0)
        self.assertIn("seal:", out)
        self.assertIn("intact", out)

    def test_check_detects_seal_mismatch(self):
        self._populate(sealed=True)
        data = json.load(open(self.path))
        data["a"]["x"] = 999
        open(self.path, "w").write(json.dumps(data))
        code, _, err = run_cli("check", self.path)
        self.assertEqual(code, 1)
        self.assertIn("mismatch", err)

    def test_seal_and_unseal_commands(self):
        self._populate()
        code, out, _ = run_cli("seal", self.path)
        self.assertEqual(code, 0)
        self.assertTrue(Dexpter.load(self.path).sealed)

        code, out, _ = run_cli("unseal", self.path)
        self.assertEqual(code, 0)
        self.assertFalse(Dexpter.load(self.path).sealed)


class ArgParsing(CliTestCase):
    def test_no_command_errors(self):
        code, _, _ = run_cli()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
