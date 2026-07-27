#!/usr/bin/env python3
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

import jinja2

env = jinja2.Environment(
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
)


def main(paths):
    rc = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                env.parse(handle.read())
        except jinja2.TemplateSyntaxError as exc:
            print(f"{path}:{exc.lineno}: Jinja syntax error: {exc.message}")
            rc = 1
        except OSError as exc:
            print(f"{path}: {exc}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
