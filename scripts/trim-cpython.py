#!/usr/bin/env python3
"""Cut a downloaded CPython down to the runtime this package ships.

Usage: trim-cpython.py <the directory bin/ and lib/ sit in>

Deletes, in place, the parts of a python-build-standalone tree nothing in this
application can reach: the shared libpython the interpreter itself does not
use, the Tcl/Tk runtime behind a GUI toolkit this project does not have, and
the installer and development tooling a shipped runtime has no work for.
Measured against cpython-3.11.16: 83 MB in, 33 MB out.

Two facts decide the shape of the file.

The first is that every delete here is a decision, and all of them can be wrong
the same silent way: the tree still runs, so nothing fails, and the package is
merely bigger than anyone meant it to be. So the removals are named patterns
carrying their reason, and a pattern that resolves to nothing stops the run. A
recursive sweep cannot do that — it cannot tell "already gone" from "upstream
renamed it", and the second one ships several megabytes nobody asked for with a
green build. The patterns say `3.*` where the tree says a minor version for
exactly that reason: a CPython bump has to be noticed here, not skipped.

The second is that only the cut tree can say whether the cut was safe. Two
extension modules sit one directory away from files this deletes, and nothing
in this project's suite reaches either. The application opens its statistics
database through `sqlite3`, and a runtime whose `sqlite3` cannot open a file is
precisely the failure a bundled interpreter exists to prevent. So once the
cutting is done the interpreter that was cut is run: it imports what the
application and its bundled libraries import, and completes a real database
round trip. A later prune that breaks the standard library then fails the
package build instead of somebody's first launch.

Two of the steps below appear in no removal list anyone wrote down, and without
both the tree comes out at 39 MB rather than 33: every `__pycache__` in it, and
a run of `strip` over the interpreter binary. The asset arrives with its symbol
table intact despite being named for a stripped variant — upstream's name means
the DWARF debugging information is gone, not that anything ran `strip`.
"""

import glob
import os
import re
import shutil
import subprocess
import sys

# What goes, and why. Nothing reads the reasons; they are here so a later cut —
# or a later restoration — has something to argue against, which is the job
# `DROPPED_PLUGINS` does in the Qt trimmer beside this file. Each reason is a
# noun phrase, because a pattern that stops resolving reports itself with one.
REMOVED = {
    # The interpreter binary embeds libpython statically and records no need
    # for the shared copy; neither does any Qt, shiboken or standard-library
    # object in the bundle. Verified by reading the dependency records and
    # again by running the whole stack with the file moved aside. The two
    # symlinks beside it name it, and would be left dangling.
    "lib/libpython3*.so*": "20.8 MB of interpreter the binary already contains",

    # There is no GUI toolkit in this package but Qt, so the Tcl and Tk runtime
    # underneath the standard library's own toolkit has nothing to serve. An
    # earlier hand trim took the Python half and left the C libraries, which is
    # 8.6 MB of the two.
    "lib/libtcl*.so": "Tcl and Tk themselves",
    "lib/tcl*": "Tcl's script library",
    "lib/tk*": "Tk's widget resources",
    "lib/itcl*": "Tcl's object system, which only Tk loads",
    "lib/thread*": "Tcl's threading extension, likewise",
    "lib/python3.*/tkinter": "the standard library's binding to Tk",
    "lib/python3.*/lib-dynload/_tkinter*.so": "the C half of that binding",

    # The installer, and the tooling a development checkout wants and an
    # installed runtime does not. Removing pip costs the package build nothing:
    # the wheels and the application are installed into this tree by a *second*
    # extraction of the same tarball, which keeps its pip precisely so that
    # this copy does not have to.
    "lib/python3.*/site-packages/pip": "pip",
    "lib/python3.*/site-packages/pip-*.dist-info": "pip's installation record",
    "lib/python3.*/site-packages/setuptools": "setuptools",
    "lib/python3.*/site-packages/setuptools-*.dist-info":
        "setuptools' installation record",
    "lib/python3.*/ensurepip": "the wheels pip is bootstrapped from",
    "lib/python3.*/idlelib": "IDLE, an editor",
    "lib/python3.*/lib2to3": "a Python 2 translator",
    "lib/python3.*/pydoc_data": "pydoc's topic texts",
    "lib/python3.*/turtledemo": "the turtle graphics demonstrations",
    "lib/python3.*/lib-dynload/_test*.so": "CPython's own test extensions",
    "include": "the C headers something would build an extension against",
    "share": "manual pages and a terminal database",
    "bin/pip*": "pip's entry points",
    "bin/idle3*": "IDLE's entry points",
    "bin/2to3*": "the translator's entry points",
    "bin/pydoc3*": "pydoc's entry points",
    # `pkg_resources` is named in the measured removal list and is deliberately
    # absent here: the pinned setuptools no longer vendors it, so a pattern for
    # it would resolve to nothing and stop every run on the first line.
}

# The extension modules a purge scoped one directory too wide takes with it.
# Both live beside files the list above removes, and neither is reachable from
# any test this project runs, so their absence would first be noticed by a
# user. They are checked as files rather than imported: see below for why the
# second one cannot be imported on a build host at all.
KEPT_EXTENSIONS = {
    "lib/python3.*/lib-dynload/_dbm*.so":
        "dbm, 1.6 MB that looks droppable and was measured not to be",
    "lib/python3.*/lib-dynload/_crypt*.so":
        "crypt, whose libcrypt.so.1 no build container here installs",
}

# What the trimmed interpreter has to be able to import for the application and
# its bundled libraries to run. `sqlite3` is the reason this interpreter is
# bundled at all — the daemon's statistics open a database with it, and the
# distribution that splits its standard library puts `sqlite3` in the half no
# declared dependency names. `dbm.ndbm` rather than `dbm`, because the package
# alone loads no extension module and would pass with `_dbm` deleted.
REQUIRED_MODULES = ("ssl", "hashlib", "lzma", "bz2", "zlib", "dbm.ndbm",
                    "select", "fcntl", "termios", "sqlite3", "ctypes",
                    "decimal", "uuid")

# Run by the interpreter under test, not by the one running this script: what
# has to be proved is the tree that ships, under the isolation flag it ships
# with. Importing is not enough on its own for a database — a round trip is
# what says the module found its library and can write a file.
#
# It runs with bytecode writing off as well, because a proof that leaves nine
# new caches in the tree it was measuring is not measuring the shipped tree.
# That is the only difference from how the package invokes this interpreter,
# and it changes nothing about what gets imported.
PROOF = """
import importlib, os, sqlite3, sys, tempfile

for name in sys.argv[1:]:
    importlib.import_module(name)

with tempfile.TemporaryDirectory() as scratch:
    database = sqlite3.connect(os.path.join(scratch, "trim.sqlite3"))
    database.execute("CREATE TABLE proof (value TEXT)")
    database.execute("INSERT INTO proof VALUES (?)", ("round trip",))
    (stored,) = database.execute("SELECT value FROM proof").fetchone()
    database.close()

if stored != "round trip":
    sys.exit(f"sqlite3 stored a row and read back {stored!r}")
"""

# The one real interpreter in bin/. Everything else there is either a symlink
# to it or a script named after it — a plain glob on the version digits also
# catches the build configuration helper, and then nothing can be stripped.
INTERPRETER_NAME = re.compile(r"python3\.[0-9]+")


def removal_targets(root):
    """Every path the removals resolve to, once all of them have."""
    targets = []
    for pattern, reason in REMOVED.items():
        found = glob.glob(os.path.join(root, pattern))
        if not found:
            sys.exit(f"trim-cpython: nothing matches {pattern} — this "
                     f"interpreter no longer keeps {reason} where the trim "
                     f"expects it, and skipping it would ship the package "
                     f"larger with nothing to show for it")
        targets += found
    return targets


def surviving_extensions(root):
    """The extension modules the removals must not have taken with them."""
    survivors = []
    for pattern, reason in KEPT_EXTENSIONS.items():
        found = glob.glob(os.path.join(root, pattern))
        if not found:
            sys.exit(f"trim-cpython: the trim removed {pattern}, which the "
                     f"standard library needs for {reason}")
        survivors += found
    return survivors


def _delete(path):
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    else:
        shutil.rmtree(path)


def sweep_pycache(root):
    """Every bytecode cache in the tree, wherever it turned out to be.

    A sweep rather than a pattern, because these directories are everywhere and
    the absence of one at any given path means nothing at all.
    """
    swept = 0
    for base, directories, _files in os.walk(root):
        for name in list(directories):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(base, name))
                directories.remove(name)
                swept += 1
    return swept


def interpreter(root):
    """The interpreter binary itself, resolved to exactly one file."""
    binaries = [path for path in glob.glob(os.path.join(root, "bin", "*"))
                if INTERPRETER_NAME.fullmatch(os.path.basename(path))
                and os.path.isfile(path) and not os.path.islink(path)]
    if len(binaries) != 1:
        sys.exit(f"trim-cpython: {root}/bin holds {len(binaries)} interpreter "
                 "binaries, and the trim can only work on one")
    return binaries[0]


def strip_interpreter(root):
    """Take the symbol table off the interpreter; ~2 MB of the 33.

    Gated on the command's exit status and on the file actually shrinking,
    never on what it printed — `file` calls this binary "not stripped" before
    the run, which is the fact the asset's own name argues against.
    """
    binary = interpreter(root)
    before = os.path.getsize(binary)
    finished = subprocess.run(["strip", binary], check=False)
    after = os.path.getsize(binary)
    if finished.returncode != 0 or after >= before:
        sys.exit(f"trim-cpython: strip exited {finished.returncode} and left "
                 f"{binary} at {after} bytes, from {before}")
    return before, after


def prove_standard_library(root):
    """Make the interpreter that was just cut run what the application needs."""
    finished = subprocess.run(
        [interpreter(root), "-I", "-B", "-c", PROOF, *REQUIRED_MODULES],
        capture_output=True, text=True, check=False)
    if finished.returncode != 0:
        sys.exit("trim-cpython: the trimmed interpreter cannot run what this "
                 f"application imports:\n{finished.stderr.strip()}")


def kept_files_and_bytes(root):
    """What is left, counted and measured, for the build log to record."""
    count = 0
    total = 0
    for base, _directories, files in os.walk(root):
        for name in files:
            count += 1
            total += os.lstat(os.path.join(base, name)).st_size
    return count, total


def main(root):
    targets = removal_targets(root)
    for path in targets:
        _delete(path)
    surviving_extensions(root)
    swept = sweep_pycache(root)
    before, after = strip_interpreter(root)
    prove_standard_library(root)

    count, total = kept_files_and_bytes(root)
    print(f"trim-cpython: removed {len(targets)} named paths and {swept} "
          f"bytecode caches, took {before - after} bytes off the interpreter, "
          f"kept {count} files totalling {total} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
