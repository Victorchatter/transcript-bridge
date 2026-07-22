"""CLI for transcript-bridge."""
import argparse
import sys

from . import FORMATS
from .loss import report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="transcript-bridge")
    parser.add_argument("file", nargs="?", help="input file path, or - for stdin")
    parser.add_argument("--from", dest="source_format", help="source format name")
    parser.add_argument("--to", dest="target_format", help="target format name")
    parser.add_argument("-o", dest="output", help="output file (default: stdout)")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any loss occurs")
    args = parser.parse_args(argv)

    if args.file is None and (args.source_format is None or args.target_format is None):
        # Special case: bare invocation lists formats, like
        # `transcript-bridge formats`.
        for name in sorted(FORMATS):
            print(name)
        return 0

    if args.file == "formats":
        for name in sorted(FORMATS):
            print(name)
        return 0

    if args.source_format is None or args.target_format is None:
        parser.error("--from and --to are required unless listing formats")

    reader, writer = _get_rw(args.source_format, args.target_format)

    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()

    turns = reader(text)
    output_text, losses = writer(turns)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)

    sys.stderr.write(report(losses) + "\n")
    if args.strict and losses:
        return 2
    return 0


def _get_rw(source, target):
    if source not in FORMATS:
        raise SystemExit(f"unknown source format: {source}")
    if target not in FORMATS:
        raise SystemExit(f"unknown target format: {target}")
    return FORMATS[source][0], FORMATS[target][1]


def _selfcheck():
    assert main(["formats"]) == 0
    print("cli selfcheck OK")


if __name__ == "__main__":
    raise SystemExit(main())
