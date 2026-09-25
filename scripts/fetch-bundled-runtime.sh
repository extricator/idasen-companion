#!/usr/bin/env bash
# Fetch the Python runtime the self-contained RPM carries -- the interpreter it
# runs on and the wheel set it imports -- and write both into that spec's
# source directory.
#
#   scripts/fetch-bundled-runtime.sh <directory to write them into>
#
# The package ships its whole Python runtime, so this is where that runtime is
# decided. rpmbuild itself then runs offline against what this writes: this
# script is the one step of the build that needs the network, and it is run
# once.
#
# Gates on exit codes only, never on the printed text of what it runs.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-python3}

# ---------------------------------------------------------------------------
# The interpreter the package runs on, pinned to one upstream release asset:
# where to get it, what it is called, and what it has to hash to. Three lines
# so that bumping it is three visible edits rather than one buried one.
#
# The release does publish a checksum list of its own, and fetching that would
# add nothing: it travels with the assets it describes, so a substituted
# release would carry a list agreeing with itself. Recording the hash here, by
# hand, at pin time, is what makes a later download answerable to what was
# reviewed -- and it is the whole of the integrity gate available, since
# upstream signs no individual asset.
# ---------------------------------------------------------------------------
INTERPRETER_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260814/cpython-3.14.7%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
INTERPRETER_ASSET="cpython-3.14.7+20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
INTERPRETER_SHA256="cefba034445d2875408d1fd4d5700ae6731563aeb54dcb39fd8164ab5c457533"

# ---------------------------------------------------------------------------
# The bundled distributions, pinned exactly. Nothing here floats: the tarball
# has to be the same bytes for a contributor and for CI, and the spec restates
# these versions in the provides it declares and the licenses it installs, so
# a range would make both of those claims untrue the first time an upstream
# released. Bump a line here and the spec's matching line together.
# ---------------------------------------------------------------------------
PINS=(
    "PySide6-Essentials==6.11.1"
    "shiboken6==6.11.1"
    "bleak==3.0.2"
    "idasen==0.13.1"
    "dbus-fast==5.0.22"
    "PyYAML==6.0.3"
    "tomlkit==0.15.1"
    "Babel==2.18.0"
    "voluptuous==0.16.0"
    # Imported by bleak on any interpreter below 3.12, and declared by it
    # under a marker saying so. Nothing below reads that declaration -- the
    # download asks for this list and for no requirement any entry of it
    # states -- so a distribution only some interpreters need has to be named
    # outright or it never arrives at all. Pinned unconditionally for that
    # reason: what this list decides is not what one machine needs but what
    # every machine the package accepts does.
    "typing-extensions==4.16.0"
)

# ---------------------------------------------------------------------------
# The one pinned distribution in this file that never ships. The app's own
# wheel is built inside the untrimmed install driver with isolation off, which
# means whatever is importable in that tree at the time is what builds it --
# and the interpreter asset has stopped bringing a build backend of its own to
# be importable. Downloaded into a directory of its own rather than folded
# into PINS above, so PINS keeps meaning exactly what the package carries: this
# pin lives only in the install driver's own site-packages, which %files never
# names, and is discarded with the rest of that tree when the build ends.
# ---------------------------------------------------------------------------
BUILD_BACKEND=(
    "setuptools==84.0.0"
)

if [ $# -ne 1 ]; then
    echo "usage: $0 <output-directory>" >&2
    exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "$(basename "$0"): curl is required and was not found" >&2
    exit 2
fi
OUTDIR=$1
mkdir -p "$OUTDIR"
OUTDIR=$(cd "$OUTDIR" && pwd)

VERSION=$("$PYTHON" -c \
    "import sys; sys.path.insert(0, 'src'); import idasen_companion; print(idasen_companion.__version__)")
TARBALL="$OUTDIR/idasen-companion-wheels-${VERSION}.tar.gz"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/wheels"
mkdir "$WORK/build-backend"

echo ">> Downloading the pinned interpreter..."
# -f is load-bearing: without it an error page from the far end is written to
# the file as though it were the asset, and nothing but the checksum below
# would ever notice.
curl -fsSL --proto '=https' --tlsv1.2 \
    -o "$WORK/$INTERPRETER_ASSET" "$INTERPRETER_URL"

echo ">> Checking it is the interpreter that was pinned..."
# Before anything unpacks it and long before anything runs it: this file is an
# executable the build then executes, so the one moment its bytes can still be
# refused is now.
if ! printf '%s  %s\n' "$INTERPRETER_SHA256" "$WORK/$INTERPRETER_ASSET" \
        | sha256sum -c - >/dev/null 2>&1; then
    echo "error: the interpreter download is not the pinned bytes." >&2
    echo "  pinned:  $INTERPRETER_SHA256" >&2
    echo "  arrived: $(sha256sum <"$WORK/$INTERPRETER_ASSET" | cut -d' ' -f1)" >&2
    exit 1
fi

mkdir "$WORK/interpreter"
tar xzf "$WORK/$INTERPRETER_ASSET" -C "$WORK/interpreter"

# Found by shape rather than by name. Which minor version this is, is stated
# once already -- in the asset the pin above names -- and a second statement of
# it here would be a second thing to remember to bump. The digits have to run
# to the end of the name: a build-configuration helper sits in the same
# directory under a name beginning exactly like the interpreter's, so a pattern
# stopping at the first digit finds both and can say which it meant about
# neither.
mapfile -t INTERPRETER < <(
    find "$WORK/interpreter/python/bin" -maxdepth 1 -type f -perm -u+x \
        -regex '.*/python3\.[0-9]+')
if [ ${#INTERPRETER[@]} -ne 1 ]; then
    echo "error: the interpreter tarball did not unpack to exactly one" \
         "interpreter binary (found ${#INTERPRETER[@]})" >&2
    exit 1
fi

echo ">> Downloading the pinned wheel set..."
# Asked for by the interpreter that will run them. Two of these distributions
# publish a separate wheel per interpreter version, and the one pip selects is
# the one it is itself -- so a build host a release or two ahead resolves a set
# that no machine this package installs on can import. It is the same reason
# the app's own runtime is bundled at all, applied to the step that decides
# what gets bundled.
#
# Built distributions only. A source distribution here would be compiled
# against whatever compiler and headers the build host has, which is the exact
# lock this package exists to remove.
#
# Resolution is switched off with it: the list above is the whole closure, the
# transitive entries named in it explicitly, so nothing is taken away by not
# asking pip to work them out -- and what ships stays a property of that list
# rather than of anything the download environment contributes.
"${INTERPRETER[0]}" -m pip download --only-binary=:all: --no-deps \
    --dest "$WORK/wheels" "${PINS[@]}"

echo ">> Checking the download is exactly the pinned distributions..."
pinned_names=""
missing=()
for pin in "${PINS[@]}"; do
    # Wheel filenames lower-case the distribution name and write every
    # separator as an underscore, so the pin has to be normalised before it
    # can be looked for.
    normalized=$(printf '%s' "${pin%%==*}" | tr '[:upper:]-' '[:lower:]_')
    pinned_names="$pinned_names $normalized"
    compgen -G "$WORK/wheels/${normalized}-*.whl" >/dev/null || missing+=("$pin")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "error: no wheel was downloaded for: ${missing[*]}" >&2
    exit 1
fi

# The other direction, which nothing checked before. A distribution that
# arrives without being asked for is installed anyway -- the spec globs this
# directory -- and then ships with no provides line naming it, no licence
# text of its own and no arm in the package's licence expression, none of
# which fails a build.
unpinned=()
for wheel in "$WORK"/wheels/*; do
    # A wheel filename is the distribution, then its version, then the tags it
    # is compatible with, all separated by the same character.
    arrived=$(basename "$wheel")
    case " $pinned_names " in
        *" ${arrived%%-*} "*) ;;
        *) unpinned+=("$arrived") ;;
    esac
done
if [ ${#unpinned[@]} -gt 0 ]; then
    echo "error: the download brought what nothing pinned: ${unpinned[*]}" >&2
    exit 1
fi

echo ">> Downloading the build backend the untrimmed install driver installs from..."
"${INTERPRETER[0]}" -m pip download --only-binary=:all: --no-deps \
    --dest "$WORK/build-backend" "${BUILD_BACKEND[@]}"

echo ">> Checking the download is exactly the pinned build backend..."
backend_pinned_names=""
backend_missing=()
for pin in "${BUILD_BACKEND[@]}"; do
    normalized=$(printf '%s' "${pin%%==*}" | tr '[:upper:]-' '[:lower:]_')
    backend_pinned_names="$backend_pinned_names $normalized"
    compgen -G "$WORK/build-backend/${normalized}-*.whl" >/dev/null \
        || backend_missing+=("$pin")
done
if [ ${#backend_missing[@]} -gt 0 ]; then
    echo "error: no wheel was downloaded for: ${backend_missing[*]}" >&2
    exit 1
fi

backend_unpinned=()
for wheel in "$WORK"/build-backend/*; do
    arrived=$(basename "$wheel")
    case " $backend_pinned_names " in
        *" ${arrived%%-*} "*) ;;
        *) backend_unpinned+=("$arrived") ;;
    esac
done
if [ ${#backend_unpinned[@]} -gt 0 ]; then
    echo "error: the download brought what nothing pinned: ${backend_unpinned[*]}" >&2
    exit 1
fi

tar czf "$TARBALL" -C "$WORK" wheels build-backend

# Under the name it was published and verified as: neither re-archived nor
# renamed. The hash above answers to those bytes under that name, and a file
# rebuilt here would carry neither.
cp "$WORK/$INTERPRETER_ASSET" "$OUTDIR/$INTERPRETER_ASSET"

echo ">> Wrote $TARBALL"
echo ">> Wrote $OUTDIR/$INTERPRETER_ASSET"
