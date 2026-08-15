#!/usr/bin/env bash
# Which interpreter compiled the bytecode this package installs, whether there
# is any, and what it is checked against.
#
#     scripts/verify-bundled-bytecode.sh <tree> <cache tag>
#
# The tag is the name an interpreter writes into every cache file it produces.
# Ask the shipped interpreter for its own rather than writing one down here:
# a minor version moved in one place and not the other then stops the build
# instead of quietly exempting the whole tree.
#
# Three properties, and every one of them regresses without failing.
#
# A cache tagged for a different interpreter is a fingerprint. It means some
# build step ran the machine's own Python out of the tree this package ships,
# which is the one thing a package carrying its own runtime must not do. 105
# such files went out in three releases; two %check steps wrote them by
# importing the app and the bundled Qt on the build host's interpreter, and
# the build packaged what it found. Nothing on a user's machine ever reads
# them. The size is not the point — the point is that the build reached
# outside the runtime it ships, and that a distribution bump moving the host's
# Python would restore exactly that, just as quietly.
#
# A source file with no cache beside it is compiled again on every process
# start, for the life of the installation. The private tree is root-owned, so
# the result cannot be written back and is thrown away; nothing raises and
# nothing logs, and both entry points pay it at every launch. Four fifths of
# this package's source shipped that way, because the installer compiles what
# it installs and nothing compiled the standard library underneath it.
#
# A cache the interpreter validates against a modification time makes the
# package's own bytes depend on the timestamps its build happened to see, and
# stops being believed the moment an unpack, a copy or a restore moves one.
# The hash-based form is checked against the source it was compiled from.
set -euo pipefail

# One outcome per exit status, named here the way the two verifiers beside
# this one name theirs, so a build log says which thing moved rather than that
# something did:
#
#   0   every cache is the shipped interpreter's, complete, and hash-checked
#   2   no tree or no tag was named, or the tree named is not there (usage)
#   10  the walk found no bytecode at all -- see the note at that check
#   20  a cache is tagged for an interpreter this package does not carry
#   30  a shipped source file has no cache beside it
#   40  a cache is validated against a timestamp rather than against its source

# Where a cache file records how it is to be validated: the byte at this
# offset, whose lowest bit is set on the hash-based form. The format is
# little-endian wherever it is written, so one byte answers this on any
# machine.
INVALIDATION_OFFSET=4
HASH_BASED_BIT=1

usage() {
    echo "usage: $(basename "$0") <tree> <cache tag>" >&2
}

# The name this cache file was written under, which is the interpreter that
# wrote it: everything between the source's name and the suffix.
tag_of() {
    local name
    name=$(basename "$1" .pyc)
    echo "${name##*.}"
}

is_hash_based() {
    local flags
    flags=$(od -An -tu1 -j "$INVALIDATION_OFFSET" -N1 -- "$1" | tr -d ' ')
    [ -n "$flags" ] && [ $((flags & HASH_BASED_BIT)) -ne 0 ]
}

main() {
    local tree=${1:-} tag=${2:-}
    if [ -z "$tree" ] || [ -z "$tag" ]; then
        usage
        return 2
    fi
    if [ ! -d "$tree" ]; then
        echo "$(basename "$0"): no such tree: $tree" >&2
        return 2
    fi

    local -a caches=() foreign=() stamped=() uncached=()
    local cache source
    while IFS= read -r -d '' cache; do
        caches+=("$cache")
    done < <(find "$tree" -type f -name '*.pyc' -print0)

    # A check whose walk stopped matching reports success having verified
    # nothing, which is worse than not having the check: it is a green light
    # nobody will look behind. The same canary the linkage verifier beside
    # this one carries, for the same reason.
    if [ "${#caches[@]}" -eq 0 ]; then
        echo "$(basename "$0"): found no bytecode anywhere under $tree" >&2
        echo "nothing was examined, so nothing was verified" >&2
        return 10
    fi

    for cache in "${caches[@]}"; do
        if [ "$(tag_of "$cache")" != "$tag" ]; then
            foreign+=("$cache")
        elif ! is_hash_based "$cache"; then
            stamped+=("$cache")
        fi
    done

    local -i sources=0
    while IFS= read -r -d '' source; do
        sources+=1
        cache="$(dirname "$source")/__pycache__/$(basename "$source" .py).$tag.pyc"
        [ -f "$cache" ] || uncached+=("$source")
    done < <(find "$tree" -type f -name '*.py' -not -path '*/__pycache__/*' -print0)

    echo "examined ${#caches[@]} bytecode caches beside $sources source files"
    echo "under $tree, against the tag $tag"

    if [ "${#foreign[@]}" -gt 0 ]; then
        printf '%s\n' "${foreign[@]}" >&2
        echo "error: the cache file(s) above were compiled by an interpreter" >&2
        echo "this package does not carry, so a build step ran the machine's" >&2
        echo "own Python out of the tree that ships." >&2
        return 20
    fi

    if [ "${#uncached[@]}" -gt 0 ]; then
        printf '%s\n' "${uncached[@]}" >&2
        echo "error: the source file(s) above ship with no bytecode beside" >&2
        echo "them, so every process that imports one compiles it again and" >&2
        echo "throws the result away -- the directory it would go in belongs" >&2
        echo "to root and the user running the app cannot write it." >&2
        return 30
    fi

    if [ "${#stamped[@]}" -gt 0 ]; then
        printf '%s\n' "${stamped[@]}" >&2
        echo "error: the cache file(s) above are validated against a source" >&2
        echo "modification time, so what this package ships depends on the" >&2
        echo "timestamps its build saw, and an unpack or a copy that moves" >&2
        echo "one silently invalidates them on the user's machine." >&2
        return 40
    fi
}

main "$@"
