#!/usr/bin/env bash
# Three questions that can only be put to a finished package.
#
#     scripts/verify-rpm-metadata.sh rpmbuild/RPMS/x86_64/idasen-companion-*.rpm
#
# Everything here is metadata rpmbuild generates rather than anything written
# in the spec, which is why none of it can be checked by reading a file: the
# requirements come from scanning what the package carries, the provides come
# from the same scan minus an exclusion, and the format comes from whatever the
# build host's rpm defaults to. A change in any of the three arrives from
# outside this repository.
#
# The other half of the pair is scripts/verify-bundled-elf.sh, which asks what
# the shipped *tree* links and requires, from inside %check where it costs
# nothing and gates every build. This one needs a built package, so it runs
# after rpmbuild -- in CI between building and publishing, so that a package
# failing it is never uploaded.
set -euo pipefail

# One outcome per exit status, named the way scripts/verify-rpm-portability.sh
# names its own:
#
#   0   the package asks for no interpreter, advertises nothing private, and
#       is written in the format its older targets read
#   2   no package was named, or the one named is not there (usage)
#   10  a query came back empty -- see the note at that check
#   20  the package is written in the newer format
#   30  the package asks the machine for a Python
#   40  the package advertises a shared object to the rest of the system
#
# The format an rpm this old can read. Both build hosts this project uses write
# it by default today, so this is not currently catching anything -- it is here
# for the day one of them stops, which would be invisible in every other way.
# The lead bytes are deliberately not what gets tested: the lead is historical
# baggage, and reading a package's format out of it tests the wrong thing.
EXPECTED_FORMAT=4

# A requirement that names an interpreter, in each of the forms one can take:
# the capability the older spec asked for, a distribution's Python package, the
# shared library a system interpreter is built around, and an interpreter named
# by path. The package carries its own and must ask for none of them -- and the
# capability in particular is the trap, since it resolves everywhere while
# being announced, on one family, by a package that does not hold the whole
# standard library.
INTERPRETER_REQUIREMENT='python\(abi\)|^python3?(-|$| )|^libpython|^/usr/(bin|libexec)/python'

# A provides line naming a shared object. The package's own name and arch, and
# the bundled(...) line it declares per vendored distribution, are the point of
# that section and stay; a soname is what must never appear, because it is an
# offer to the whole machine to resolve against a private copy of Qt that is
# upgraded on this app's schedule rather than the distribution's.
PRIVATE_SONAME='\.so'

usage() {
    echo "usage: $(basename "$0") <path-to-rpm>" >&2
}

main() {
    local package=${1:-}
    if [ -z "$package" ]; then
        usage
        return 2
    fi
    if [ ! -f "$package" ]; then
        echo "$(basename "$0"): no such package: $package" >&2
        return 2
    fi
    if ! command -v rpm >/dev/null 2>&1; then
        echo "$(basename "$0"): rpm is required and was not found" >&2
        return 2
    fi

    echo "package: $package"

    # Every query below is asked of a package and of nothing else, and is
    # guarded for a failed or empty answer as well as for a wrong one. Both
    # halves matter. A grep over nothing finds nothing, which reads exactly
    # like the package being clean -- and handed something that is not a
    # package at all, rpm's default is to read it as a *list* of packages to
    # query instead, so an argument that missed could quietly produce a clean
    # report about some entirely other file.
    local format
    format=$(rpm -qp --nomanifest --qf '%{rpmformat}\n' "$package" 2>/dev/null) \
        || format=""
    if [ -z "$format" ]; then
        echo "error: the package will not say what format it is written in" >&2
        return 10
    fi
    if [ "$format" != "$EXPECTED_FORMAT" ]; then
        echo "error: the package is written in format $format, not $EXPECTED_FORMAT," >&2
        echo "which the older lines this package targets cannot read" >&2
        return 20
    fi
    echo "format: $format"

    local requires interpreter
    requires=$(rpm -qpR --nomanifest "$package" 2>/dev/null) || requires=""
    if [ -z "$requires" ]; then
        echo "error: the package declares no requirements at all, which no" >&2
        echo "package carrying Qt does -- the query answered nothing" >&2
        return 10
    fi
    interpreter=$(printf '%s\n' "$requires" \
        | grep -iE "$INTERPRETER_REQUIREMENT" || true)
    if [ -n "$interpreter" ]; then
        echo "$interpreter" >&2
        echo "error: the requirement(s) above ask the machine for a Python." >&2
        echo "This package carries its own interpreter, so a machine that has" >&2
        echo "none is one it is meant to install on." >&2
        return 30
    fi
    echo "requires: $(printf '%s\n' "$requires" | wc -l) entries, none an interpreter"

    local provides sonames
    provides=$(rpm -qp --nomanifest --provides "$package" 2>/dev/null) \
        || provides=""
    if [ -z "$provides" ]; then
        echo "error: the package provides nothing at all, not even its own" >&2
        echo "name and arch -- the query answered nothing" >&2
        return 10
    fi
    sonames=$(printf '%s\n' "$provides" | grep -E "$PRIVATE_SONAME" || true)
    if [ -n "$sonames" ]; then
        echo "$sonames" >&2
        echo "error: the provides above offer a shared object out of the" >&2
        echo "private tree to the rest of the machine, where another package" >&2
        echo "could come to resolve against a copy of Qt this app upgrades." >&2
        return 40
    fi
    echo "provides: $(printf '%s\n' "$provides" | wc -l) entries, none a soname"
}

main "$@"
