#!/bin/sh
# Start one of the app's three entry points on the interpreter this package
# carries.
#
# The package ships a complete Python of its own — the interpreter and every
# library the app imports — in a private directory, so there is nothing to
# choose here and nothing to look for on the machine. A console_scripts
# wrapper still cannot do this job: pip writes the interpreter that ran it into
# a shebang, and that is the build host's, which is the one interpreter this
# package must never run on. The spec fills the path in below at install time.
#
# The interpreter is run isolated, and that switch is what makes the bundled
# copies win: it takes the launch directory, the user's own per-user library
# directory and every environment variable naming a Python search path off the
# search path, leaving the interpreter's own directories and nothing else.
#
# There is deliberately no variable for pointing this somewhere else. Its
# meaning would be "choose among the machine's interpreters", and there is no
# longer a choice: another interpreter, run isolated, would see none of the
# bundled libraries and fail on its first import. A variable that can only
# break a working installation is worse than no variable.
set -e

PYTHON=@PYTHON@

if [ ! -x "$PYTHON" ]; then
    echo "idasen-companion cannot run: the Python it ships is missing from" >&2
    echo "$PYTHON. Reinstall the package." >&2
    exit 1
fi

exec "$PYTHON" -I -m @ENTRY@ "$@"
