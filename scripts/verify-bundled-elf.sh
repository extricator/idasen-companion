#!/usr/bin/env bash
# What the tree this package ships is allowed to link, how new a C library it
# is allowed to ask for, and what weight it is allowed to carry that nothing
# reads.
#
#     scripts/verify-bundled-elf.sh <tree>
#
# Both are facts that were measured once and then designed around, and both can
# stop being true without a line of this repository changing: a PySide6 or
# CPython release is enough. Neither would fail loudly. The package would build,
# install, and then not start on somebody else's machine.
#
# The linkage half is the load-bearing one. The interpreter that ships here has
# libpython compiled into the executable, which is the whole reason the 20.8 MB
# shared copy of it is not in the package. Nothing in Qt, PySide6, shiboken6 or
# the interpreter's own extension modules references that library today -- that
# was measured over the real packaged tree, not assumed -- and the day one of
# them does, the package is short a library it never noticed it needed.
#
# The symbol-version half is the same shape of claim pointed at the other end
# of the range: a binary asking for a symbol version newer than the oldest
# distribution line this package reaches will not load there, and nothing on a
# current build host would ever notice.
#
# The third half -- the symbol tables -- is a claim about a policy rather than
# about a file. rpm's own build-root strip pass is switched off for this
# package because it cannot be told to spare the one binary it corrupts, and
# scripts/strip-bundled-tree.sh does that pass by hand instead. Nothing else
# would notice if that stopped happening: the package would build, install and
# run, merely carrying whatever every dependency's build host left behind. So
# what is asserted here is the result rather than the step, and a binary is
# excused only by carrying the rewrite markers that made it exempt.
set -euo pipefail

# The ceilings. Each is a statement about a *distribution line* rather than
# about a number, which is also the argument anyone raising one has to make.
#
# The oldest line this package reaches is the enterprise 9 generation, whose
# glibc is 2.34 -- so 2.34 is not a value the shipped binaries happen to sit
# at, it is that line, and sitting exactly on it is correct rather than
# alarming. (The two SUSE targets are newer: Leap 15.6 is 2.38.) The symbol
# comes from Qt, not from the interpreter, whose own floor is lower, so the
# thing that moves this is a Qt bump. Raising it means dropping enterprise 9,
# which is a decision about who can install the package.
GLIBC_CEILING=2.34
# The three toolchain families, at what the Qt in the package requires today.
# They travel with the compiler that built the PySide6 wheels rather than with
# a distribution, so a rise here is a wheel built on a newer toolchain -- worth
# stopping on for the same reason, since the runtime that has to answer for it
# is the one on the user's machine.
GLIBCXX_CEILING=3.4.29
CXXABI_CEILING=1.3.13
GCC_CEILING=3.0

# One outcome per exit status, named here the way
# scripts/verify-rpm-portability.sh names its own, so a build log says which
# thing moved rather than that something did:
#
#   0   the tree links nothing it must not and asks for nothing too new
#   2   no tree was named, or the one named is not there (usage)
#   10  the walk found no ELF file at all -- see the note at that check
#   20  a shipped file links the interpreter's shared library
#   30  a shipped file requires a glibc newer than the ceiling above
#   31  ... a libstdc++
#   32  ... a C++ ABI
#   33  ... a libgcc
#   40  a shipped file still carries a symbol table nothing took off it
#
# Family, its ceiling, and the status that names it.
SYMBOL_FAMILIES=(
    "GLIBC|${GLIBC_CEILING}|30"
    "GLIBCXX|${GLIBCXX_CEILING}|31"
    "CXXABI|${CXXABI_CEILING}|32"
    "GCC|${GCC_CEILING}|33"
)

# The four bytes every ELF file starts with.
ELF_MAGIC=$'\177ELF'

usage() {
    echo "usage: $(basename "$0") <tree>" >&2
}

# Read those four bytes rather than asking a program what the file is. The
# answer is the same one `file` would give -- it is where `file` gets it -- and
# this way a build that already declares two program paths does not have to
# declare a third for a four-byte comparison.
is_elf() {
    local magic=
    IFS= read -r -n4 magic < "$1" 2>/dev/null || true
    [ "$magic" = "$ELF_MAGIC" ]
}

# True when the first version is newer than the second. Ordered by `sort -V`
# and never as a string or a number: 2.9 is above 2.34 under both of those, and
# under neither is that what a symbol version means.
version_exceeds() {
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n1)" != "$2" ]
}

main() {
    local tree=${1:-}
    if [ -z "$tree" ]; then
        usage
        return 2
    fi
    if [ ! -d "$tree" ]; then
        echo "$(basename "$0"): no such tree: $tree" >&2
        return 2
    fi

    local workdir
    workdir=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$workdir'" EXIT
    local headers="$workdir/headers" symbols="$workdir/symbols"
    local sections="$workdir/sections" table="$workdir/table"
    : > "$symbols"

    # Everything the tree holds, shared objects and executables alike. The
    # interpreter is the file this matters most for and it is neither named
    # like a library nor built like one, so a walk that went looking for a
    # suffix would skip exactly the binary the design rests on.
    local examined=0 spared=0 path
    local -a linked=() unstripped=()
    while IFS= read -r -d '' path; do
        is_elf "$path" || continue
        examined=$((examined + 1))

        objdump -p "$path" > "$headers" 2>/dev/null || true
        if grep -q 'NEEDED.*libpython' "$headers"; then
            linked+=("$path")
        fi

        # Excused by its own layout rather than by its path: the rewrite
        # markers are what made the interpreter trim decline to strip it, so
        # a file that stops carrying them stops being excused here too, and a
        # bundled library that starts carrying them is excused without
        # anybody having to come back and name it.
        objdump -h "$path" > "$sections" 2>/dev/null || : > "$sections"
        objdump -t "$path" > "$table" 2>/dev/null || : > "$table"
        if grep -q '\.bolt\.org' "$sections"; then
            spared=$((spared + 1))
        elif ! grep -qx 'no symbols' "$table"; then
            unstripped+=("$path")
        fi

        objdump -T "$path" 2>/dev/null \
            | grep -oE '(GLIBC|GLIBCXX|CXXABI|GCC)_[0-9]+(\.[0-9]+)*' \
            >> "$symbols" || true
    done < <(find "$tree" -type f -print0)

    # A check whose walk stopped matching reports success having verified
    # nothing, which is worse than not having the check: it is a green light
    # nobody will look behind. This project has been bitten by that once
    # already, in its secret scanner.
    if [ "$examined" -eq 0 ]; then
        echo "$(basename "$0"): found no ELF file anywhere under $tree" >&2
        echo "nothing was examined, so nothing was verified" >&2
        return 10
    fi
    echo "examined $examined ELF files under $tree, $spared of them rewritten"

    if [ "${#unstripped[@]}" -gt 0 ]; then
        printf '%s\n' "${unstripped[@]}" >&2
        echo "error: the file(s) above still carry a symbol table. rpm's own" >&2
        echo "build-root strip pass is switched off for this package, because" >&2
        echo "it cannot be told to spare the one binary it corrupts, and" >&2
        echo "scripts/strip-bundled-tree.sh does that pass by hand instead --" >&2
        echo "so a file arriving here unstripped is one that pass no longer" >&2
        echo "reaches, and the package is shipping weight nothing reads." >&2
        return 40
    fi

    if [ "${#linked[@]}" -gt 0 ]; then
        printf '%s\n' "${linked[@]}" >&2
        echo "error: the file(s) above link the interpreter's shared library," >&2
        echo "which this package does not ship -- the interpreter it carries" >&2
        echo "has that code compiled in, and dropping the 20.8 MB shared copy" >&2
        echo "is only correct while nothing here references it. Something in" >&2
        echo "Qt, PySide6 or the standard library now does." >&2
        return 20
    fi

    local entry family ceiling status highest offending=0
    for entry in "${SYMBOL_FAMILIES[@]}"; do
        IFS='|' read -r family ceiling status <<< "$entry"
        highest=$(grep -oE "^${family}_[0-9.]+$" "$symbols" \
            | sed "s/^${family}_//" | sort -V | tail -n1 || true)
        if [ -z "$highest" ]; then
            echo "$family: required by nothing in the tree"
            continue
        fi
        if version_exceeds "$highest" "$ceiling"; then
            echo "$family: requires $highest, above the ceiling of $ceiling" >&2
            [ "$offending" -ne 0 ] || offending=$status
        else
            echo "$family: requires $highest, ceiling $ceiling"
        fi
    done

    if [ "$offending" -ne 0 ]; then
        echo "error: the tree asks for a symbol version newer than the oldest" >&2
        echo "distribution line this package reaches, so it will not load" >&2
        echo "there -- and nothing on a current build host would notice." >&2
        return "$offending"
    fi
}

main "$@"
