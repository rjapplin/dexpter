import argparse
import json
import sys
import warnings

from .core import Dexpter, DexpterError


def _show_warning(message, category, filename, lineno, file=None, line=None):
    print(f"warning: {message}", file=sys.stderr)


def main(argv=None):
    warnings.showwarning = _show_warning

    parser = argparse.ArgumentParser(
        prog="dexpter", description="Lightweight JSON-backed data science experiment tracker"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a new DEXPTER database file")
    p_init.add_argument("path")
    p_init.add_argument(
        "--require",
        action="append",
        default=[],
        dest="required_fields",
        metavar="FIELD",
        help="Field that must be set on every experiment (repeatable)",
    )
    p_init.add_argument(
        "--seal",
        action="store_true",
        help="Turn on tamper-evidence: warn on load if the file changed outside dexpter",
    )

    p_list = sub.add_parser("list", help="List experiments in a database")
    p_list.add_argument("path")

    p_show = sub.add_parser("show", help="Show a single experiment's full record")
    p_show.add_argument("path")
    p_show.add_argument("experiment_id")

    p_require = sub.add_parser("require", help="View or change a database's required fields")
    p_require.add_argument("path")
    p_require.add_argument(
        "--add", action="append", default=[], dest="add_fields", metavar="FIELD"
    )
    p_require.add_argument(
        "--remove", action="append", default=[], dest="remove_fields", metavar="FIELD"
    )

    p_link = sub.add_parser("link", help="Link two experiments together")
    p_link.add_argument("path")
    p_link.add_argument("id_a")
    p_link.add_argument("id_b")

    p_unlink = sub.add_parser("unlink", help="Remove a link between two experiments")
    p_unlink.add_argument("path")
    p_unlink.add_argument("id_a")
    p_unlink.add_argument("id_b")

    p_links = sub.add_parser("links", help="List the experiments linked to one experiment")
    p_links.add_argument("path")
    p_links.add_argument("experiment_id")

    p_check = sub.add_parser(
        "check", help="Check a database file for structural problems / tampering"
    )
    p_check.add_argument("path")

    p_seal = sub.add_parser("seal", help="Turn on tamper-evidence (content hashing)")
    p_seal.add_argument("path")

    p_unseal = sub.add_parser("unseal", help="Turn off tamper-evidence")
    p_unseal.add_argument("path")

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            db = Dexpter.init(
                args.path, required_fields=args.required_fields, sealed=args.seal
            )
            print(f"Initialized DEXPTER database at {args.path}")
            if db.required_fields:
                print(f"required fields: {', '.join(db.required_fields)}")
            if db.sealed:
                print("sealed: on")

        elif args.command == "list":
            db = Dexpter.load(args.path)
            if db.required_fields:
                print(f"required fields: {', '.join(db.required_fields)}")
            if not len(db):
                print("(no experiments logged)")
            for exp_id, record in db.experiments.items():
                n = len(db.links(exp_id))
                links_col = f"\tlinks={n}" if n else ""
                print(
                    f"{exp_id}\tcreated={record.get('created_at')}"
                    f"\tupdated={record.get('updated_at')}{links_col}"
                )

        elif args.command == "show":
            db = Dexpter.load(args.path)
            record = db.get(args.experiment_id)
            if record is None:
                print(f"No experiment '{args.experiment_id}' found", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(record, indent=2, default=str))
            linked = db.links(args.experiment_id)
            if linked:
                # stderr so `show ... | jq` still gets clean JSON on stdout
                print(f"links: {', '.join(linked)}", file=sys.stderr)

        elif args.command == "require":
            db = Dexpter.load(args.path)
            if not args.add_fields and not args.remove_fields:
                print(f"required fields: {', '.join(db.required_fields) or '(none)'}")
            else:
                new_fields = [f for f in db.required_fields if f not in args.remove_fields]
                for f in args.add_fields:
                    if f not in new_fields:
                        new_fields.append(f)
                gaps = db.set_required_fields(new_fields)
                print(f"required fields: {', '.join(new_fields) or '(none)'}")
                if gaps:
                    print("warning: existing experiments missing new required field(s):")
                    for exp_id, missing in gaps.items():
                        print(f"  {exp_id}: {', '.join(missing)}")

        elif args.command == "link":
            db = Dexpter.load(args.path)
            db.link(args.id_a, args.id_b)
            print(f"linked {args.id_a} <-> {args.id_b}")

        elif args.command == "unlink":
            db = Dexpter.load(args.path)
            db.unlink(args.id_a, args.id_b)
            print(f"unlinked {args.id_a} <-> {args.id_b}")

        elif args.command == "links":
            db = Dexpter.load(args.path)
            if db.get(args.experiment_id) is None:
                print(f"No experiment '{args.experiment_id}' found", file=sys.stderr)
                sys.exit(1)
            linked = db.links(args.experiment_id)
            if not linked:
                print("(no links)")
            for exp_id in linked:
                print(exp_id)

        elif args.command == "check":
            report = Dexpter.validate(args.path)
            for msg in report["errors"]:
                print(f"error:   {msg}", file=sys.stderr)
            for msg in report["warnings"]:
                print(f"warning: {msg}", file=sys.stderr)
            if report["seal"] == "ok":
                print("seal:    intact")
            elif report["seal"] == "mismatch":
                print(
                    "error:   sealed database changed outside dexpter (hash mismatch)",
                    file=sys.stderr,
                )
            clean = not report["errors"] and not report["warnings"]
            if clean and report["seal"] in ("ok", "unsealed"):
                print("ok: no problems found")
            if report["errors"] or report["seal"] == "mismatch":
                sys.exit(1)

        elif args.command == "seal":
            db = Dexpter.load(args.path)
            db.seal()
            print(f"sealed {args.path}")

        elif args.command == "unseal":
            db = Dexpter.load(args.path)
            db.unseal()
            print(f"unsealed {args.path}")
    except DexpterError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
