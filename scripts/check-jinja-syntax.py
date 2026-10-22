#!/usr/bin/env python3
# Copyright (c) 2026 Robert August Vincent II <pillarsdotnet@gmail.com>
"""Check Jinja2 template (.j2) files for syntax errors.

ansible-lint does not parse the bodies of standalone .j2 files, so this
pre-commit hook does it directly. env.parse() builds the template AST and
raises TemplateSyntaxError on malformed markup ({{ ... unclosed, bad {% %},
etc.) without needing Ansible's filters/vars to be defined. The do and
loopcontrols extensions mirror what Ansible enables so valid templates do not
false-positive. Files are read as UTF-8 explicitly so the check works even
under a non-UTF-8 locale.

Usage: check-jinja-syntax.py FILE.j2 [FILE.j2 ...]
"""

import sys
from pathlib import Path

import jinja2

# This environment only parses templates to validate their syntax; nothing is
# ever rendered, so autoescape - an output-time HTML concern - does not apply.
env = jinja2.Environment(  # noqa: S701
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
)


def check_template(path: str) -> str | None:
    """Parse one template file.

    Args:
        path: The template file to parse.

    Returns:
        An error message if the file is unreadable or malformed, else None.

    """
    try:
        env.parse(Path(path).read_text(encoding="utf-8"))
    except jinja2.TemplateSyntaxError as exc:
        return f"{path}:{exc.lineno}: Jinja syntax error: {exc.message}"
    except OSError as exc:
        return f"{path}: {exc}"
    return None


def main(paths: list[str]) -> int:
    """Check every template named on the command line.

    Args:
        paths: The template files to check.

    Returns:
        The process exit status: 0 if every file parsed, 1 otherwise.

    """
    rc = 0
    for path in paths:
        error = check_template(path)
        if error is not None:
            # Reporting failures on stdout is this lint script's whole job.
            print(error)  # noqa: T201
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
