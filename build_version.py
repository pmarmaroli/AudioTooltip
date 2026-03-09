"""
Build helper: read or patch the version string in main.py.

Usage:
    python build_version.py --read
        Prints the current version (e.g. 3.0.0) to stdout and exits 0.
        Exits 1 if not found.

    python build_version.py --patch <version>
        Validates <version> matches MAJOR.MINOR.PATCH, then patches main.py.
        Exits 0 on success, 1 on failure.
"""

import re
import sys

MAIN_PY = "main.py"
VERSION_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)(?= - Audio Analysis Tool)")
VERSION_FORMAT = re.compile(r"^\d+\.\d+\.\d+$")


def read_version():
    try:
        content = open(MAIN_PY, encoding="utf-8").read()
        m = VERSION_PATTERN.search(content)
        if m:
            print(m.group(1))
            return 0
        print("unknown")
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def patch_version(new_version):
    if not VERSION_FORMAT.match(new_version):
        print(
            f"ERROR: Invalid version '{new_version}'. Expected MAJOR.MINOR.PATCH (e.g. 3.1.0)",
            file=sys.stderr,
        )
        return 1
    try:
        content = open(MAIN_PY, encoding="utf-8").read()
        new_content = VERSION_PATTERN.sub(f"v{new_version}", content)
        if new_content == content:
            print("ERROR: Version pattern not found in main.py", file=sys.stderr)
            return 1
        open(MAIN_PY, "w", encoding="utf-8").write(new_content)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--read":
        sys.exit(read_version())
    elif len(sys.argv) == 3 and sys.argv[1] == "--patch":
        sys.exit(patch_version(sys.argv[2]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
