#!/usr/bin/env bash
# The strip the build root's own policy would have run, scoped by hand.
#
#     scripts/strip-bundled-tree.sh <tree>
#
# rpm's automatic strip pass has to be switched off for this package: it walks
# the whole build root, and one binary in this tree -- the interpreter -- is
# laid out by BOLT, which every strip implementation tried against it corrupts
# rather than shrinks. rpm offers no way to except a single path from that
# policy, so switching it off spares every ELF file the package carries, not
# just the one that needs sparing: Qt's libraries, PySide6's extension
# modules, ICU's tables, the standard library's own extension modules. This
# does for all of those what the policy would have done, one file at a time,
# and leaves alone the one that must be.
#
# What decides the exemption is the file's own layout and never its path.
# BOLT's rewrite markers are the same signal scripts/trim-cpython.py branches
# on before deciding not to strip the interpreter, so an asset that stops
# being laid out that way gets its strip back here with nothing to change --
# and a bundled library that ever arrives laid out that way is spared for the
# same reason rather than corrupted for want of a rule.
#
# The bytes are not the argument. They are worth having -- ICU alone arrives
# with about two megabytes of symbol table -- but the reason this exists is
# that an unstripped tree has no floor: the next dependency can turn up
# carrying whatever its build host left on it, and without a pass here that
# ships with a green build and nothing said. scripts/verify-bundled-elf.sh is
# the other half of that, and refuses a tree where anything but a rewritten
# binary still carries a symbol table -- so this stopping quietly is not among
# the ways it can fail.
set -euo pipefail

# One outcome per exit status, named the way the verifiers beside this file
# name their own, so a build log says which thing moved rather than that
# something did:
#
#   0   every object that could be stripped is
#   2   no tree was named, or the one named is not there (usage)
#   10  the walk found no ELF file at all -- see the note at that check
#   20  strip failed on a file this handed it

# The four bytes every ELF file starts with. Read directly rather than asked
# of a program, for the reason the ELF verifier beside this file gives: a
# build that already declares two program paths should not have to declare a
# third for a four-byte comparison.
ELF_MAGIC=$'\177ELF'

usage() {
    echo "usage: $(basename "$0") <tree>" >&2
}

is_elf() {
    local magic=
    IFS= read -r -n4 magic < "$1" 2>/dev/null || true
    [ "$magic" = "$ELF_MAGIC" ]
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

    # Both readings are taken into a variable rather than piped into a
    # matcher: a reader closing the pipe early is indistinguishable from one
    # that failed once the pipeline's status is what decides, and here that
    # would read as "no markers found" on exactly the binary this must not
    # touch.
    local examined=0 stripped=0 spared=0 path sections symbols
    while IFS= read -r -d '' path; do
        is_elf "$path" || continue
        examined=$((examined + 1))

        sections=$(objdump -h "$path" 2>/dev/null) || sections=
        case $sections in
            *.bolt.org*)
                echo "left alone, rewritten by BOLT: $path"
                spared=$((spared + 1))
                continue
                ;;
        esac

        symbols=$(objdump -t "$path" 2>/dev/null) || symbols=
        case $symbols in
            *"no symbols"*) continue ;;
        esac

        if ! strip "$path"; then
            echo "$(basename "$0"): strip failed on $path" >&2
            return 20
        fi
        stripped=$((stripped + 1))
    done < <(find "$tree" -type f -print0)

    # A pass whose walk stopped matching does nothing and says it did it
    # successfully, which is worse than not having the pass: it is a green
    # light nobody will look behind. This project has been bitten by that
    # once already, in its secret scanner.
    if [ "$examined" -eq 0 ]; then
        echo "$(basename "$0"): found no ELF file anywhere under $tree" >&2
        echo "nothing was examined, so nothing was stripped" >&2
        return 10
    fi
    echo "examined $examined ELF files under $tree:" \
         "stripped $stripped, left $spared alone"
}

main "$@"
