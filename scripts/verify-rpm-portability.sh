#!/usr/bin/env bash
# Install a built RPM in throwaway rootless containers, then start the daemon
# in each one and require it to still be there afterwards.
#
#     scripts/verify-rpm-portability.sh rpmbuild/RPMS/x86_64/idasen-companion-*.rpm
#
# The package carries its own Python -- the interpreter and every library it
# imports, Qt included -- and asks the machine it lands on for nothing but
# sonames. That is a claim about every distribution nobody here develops on,
# and it breaks quietly: a Qt bump or a newly linked library changes the
# generated dependency list, the build stays green, and the package simply
# stops installing somewhere. This is what notices.
#
# Installing is not the interesting half. A package whose transaction resolves
# and whose daemon then exits on its first tick is the failure this exists to
# catch, so every image gets a real session bus and a simulated desk, and the
# process has to survive a settle period.
set -euo pipefail

# Evidence that one artifact installs and runs beyond the machine that built
# it. This is not a support matrix and not a build matrix -- nothing in the
# build depends on these images, they are consumers of a finished package --
# and it is not a list to publish. No output of this script belongs in the
# README as a set of distributions this project supports.
#
# What the list is organised by is *lineage*: distributions that inherit a
# packaging tradition from the same ancestor share their answers, so a second
# member of one proves much less than a first member of another. Two lineages
# are covered, and the entries say which is which:
#
#   Red Hat -- Fedora 43 and AlmaLinux 10 are the current-Fedora and
#              enterprise-10 generations of that tradition. Rocky 9 is the
#              strongest of the five and is not a duplicate of AlmaLinux: its
#              own `python3` is 3.9, which cannot run this app at all, and its
#              libraries are the oldest set the package reaches -- the symbol
#              versions the build asserts are chosen for exactly this line. A
#              package that starts there started on the interpreter it
#              brought, on the oldest libraries it claims to reach.
#   SUSE    -- a different tradition in the two places that reach this
#              package: `zypper` resolves and installs, and the standard
#              library arrives in two packages rather than one, with the half
#              that answers for the interpreter not the half holding
#              `sqlite3` -- which the daemon keeps its statistics in. An
#              installation there used to resolve, install, and leave the
#              machine unable to run the app. Leap 15.6 and Tumbleweed are
#              that tradition standing still and moving.
#
# No entry names an interpreter, and none can: the package brings its own and
# runs nothing else, so the machine's own Python is not a variable of this
# test any more. Every image is therefore asked two questions that could not
# be asked while the package borrowed one -- whether the transaction brought a
# Python with it, and whether the desk's statistics genuinely write and read
# back on the interpreter that arrived instead. The SUSE pair is where those
# two matter most, but a Python arriving anywhere is the same regression, and
# asking costs one query.
#
# Each entry names the outcome it is expected to reach, so a change in either
# direction is a failure rather than a silent new normal. Growing the list
# costs a pull and a full dependency transaction on every build, so grow it
# only for a lineage that is not represented, or for something about the
# package that nothing else here reaches.
IMAGES=(
    "registry.fedoraproject.org/fedora:43|runs"
    "docker.io/library/almalinux:10|runs"
    "docker.io/rockylinux/rockylinux:9|runs"
    "docker.io/opensuse/tumbleweed:latest|runs"
    "docker.io/opensuse/leap:15.6|runs"
)

# The outcomes an entry may declare. `runs` is the daemon still alive after
# the settle period. `refused` is the launcher declining to start because the
# interpreter the package carries is not where the package put it -- a broken
# installation, which is not a crash and must not be reported as one. No entry
# declares it and none should; it is kept so that an image reaching it is
# named for what happened rather than filed under a general failure. Every
# other outcome below is a defect and cannot be declared.
DECLARABLE_OUTCOMES="runs refused"

# How long the daemon has to fall over before it is believed. It reaches its
# first automation tick and its first status broadcast well inside this.
SETTLE_SECONDS=10

repository_root() {
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
}

# The container's exit status is the only thing that crosses the boundary
# reliably, so the outcome is encoded in it and named again here.
outcome_for_status() {
    case "$1" in
        0)   echo "runs" ;;
        10)  echo "install-failed" ;;
        11)  echo "no-package-manager" ;;
        12)  echo "no-session-bus" ;;
        13)  echo "python-package-arrived" ;;
        14)  echo "bundled-libraries-failed" ;;
        20)  echo "refused" ;;
        21)  echo "launcher-failed" ;;
        30)  echo "version-mismatch" ;;
        40)  echo "daemon-exited" ;;
        41)  echo "no-startup-line" ;;
        50)  echo "statistics-dead" ;;
        124) echo "timed-out" ;;
        *)   echo "crashed" ;;
    esac
}

usage() {
    echo "usage: $(basename "$0") <path-to-rpm>" >&2
}

main() {
    local root package_path package_dir package_file package_version
    root=$(repository_root)

    package_path=${1:-}
    if [ -z "$package_path" ]; then
        usage
        return 2
    fi
    if [ ! -f "$package_path" ]; then
        echo "$(basename "$0"): no such package: $package_path" >&2
        return 2
    fi
    if ! command -v podman >/dev/null 2>&1; then
        echo "$(basename "$0"): podman is required and was not found" >&2
        return 2
    fi

    package_dir=$(cd -- "$(dirname -- "$package_path")" && pwd)
    package_file=$(basename -- "$package_path")

    # Read from the package's one source of version truth, the way the
    # workflows already do. Restating the number here would quietly add this
    # file to the set a release has to move, and the test that holds those in
    # step does not look at scripts.
    package_version=$(python3 -c \
        "import sys; sys.path.insert(0, sys.argv[1]); import idasen_companion; print(idasen_companion.__version__)" \
        "$root/src")

    local workdir
    workdir=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$workdir'" EXIT
    write_container_script "$workdir/in-container.sh"

    echo "package: $package_dir/$package_file"
    echo "version: $package_version"
    echo

    local -a summary=()
    local failures=0
    local entry image expected status actual verdict

    for entry in "${IMAGES[@]}"; do
        IFS='|' read -r image expected <<< "$entry"
        case " $DECLARABLE_OUTCOMES " in
            *" $expected "*) ;;
            *)
                echo "$image declares an outcome this script does not know: $expected" >&2
                return 2
                ;;
        esac

        echo "===== $image (expecting: $expected) ====="
        status=0
        # Labelling is switched off rather than relabelling the mounts: `:z`
        # rewrites the host's own files, and one of them is a package a
        # release publishes. Nothing outside the container changes this way.
        podman run --rm \
            --security-opt label=disable \
            -v "$package_dir:/package:ro" \
            -v "$workdir/in-container.sh:/in-container.sh:ro" \
            "$image" \
            /bin/sh /in-container.sh \
            "/package/$package_file" "$package_version" "$SETTLE_SECONDS" \
            || status=$?
        actual=$(outcome_for_status "$status")

        if [ "$actual" = "$expected" ]; then
            verdict="ok"
        else
            verdict="MISMATCH"
            failures=$((failures + 1))
        fi
        echo "----- $image: $actual (expected $expected)"
        echo
        summary+=("$(printf '%-46s %-10s %-20s %s' \
            "$image" "$expected" "$actual" "$verdict")")
    done

    echo "===== summary ====="
    printf '%-46s %-10s %-20s %s\n' "image" "expected" "actual" ""
    local line
    for line in "${summary[@]}"; do
        echo "$line"
    done

    if [ "$failures" -ne 0 ]; then
        echo
        echo "$failures image(s) reached an outcome they were not expected to." >&2
        return 1
    fi
    echo
    echo "The package installs and runs on every image listed above."
}

# Written out rather than passed as a command line: it is a whole program, and
# quoting it through `podman run` once per image is how it would come to
# differ between images.
write_container_script() {
    cat > "$1" <<'IN_CONTAINER'
#!/bin/sh
# Runs inside the container, on whatever /bin/sh the image has. Reports what
# happened through its exit status; the host names the codes.
#
#     in-container.sh <package> <expected-version> <settle-seconds>
set -u

PACKAGE=$1
EXPECTED_VERSION=$2
SETTLE_SECONDS=$3

# The package manager is the one thing that differs by lineage, so it is the
# one thing named per lineage. Two operations are wanted: a local package file,
# and the session bus, whose package is named after neither the program this
# needs nor anything else predictable.
if command -v dnf >/dev/null 2>&1; then
    install_file() { dnf install -y "$1"; }
    # A path is a capability like any other to dnf, so ask for the program.
    install_session_bus() { dnf install -y /usr/bin/dbus-run-session; }
elif command -v zypper >/dev/null 2>&1; then
    # A build's own output is unsigned, and zypper will not install one
    # without being told that is expected. It also reads a path argument as a
    # file to install rather than as a capability to resolve — and its
    # metadata does not index that path either — so the session bus is asked
    # for by package name, which moved between the two SUSE lines.
    install_file() {
        zypper --non-interactive install --allow-unsigned-rpm "$1"
    }
    install_session_bus() {
        zypper --non-interactive install dbus-1-daemon \
            || zypper --non-interactive install dbus-1
    }
else
    exit 11
fi

# Both traditions build on the same package database, so one query answers on
# either: the names of the installed packages that are somebody's Python. Asked
# either side of the transaction, the two answers are the claim this package is
# built around -- that it brings its own interpreter and takes none.
if ! command -v rpm >/dev/null 2>&1; then
    echo "--- nothing here can say what is installed"
    exit 11
fi
python_packages() {
    rpm -qa --queryformat '%{NAME}\n' | grep '^python' | LC_ALL=C sort
}
# Three of these images carry no Python at all, so the two sets compared below
# are legitimately empty on them -- and an empty set is also what a query that
# failed returns. Ask once for the whole database, where an empty answer can
# only mean the question did not reach it.
if [ "$(rpm -qa --queryformat '%{NAME}\n' | wc -l)" -lt 1 ]; then
    echo "--- this machine reports no installed packages whatsoever"
    exit 11
fi

python_packages > /tmp/python-packages-before

echo "--- installing"
install_file "$PACKAGE" || exit 10

python_packages > /tmp/python-packages-after

echo "--- Python packages before the install"
cat /tmp/python-packages-before
echo "--- and after it"
cat /tmp/python-packages-after
if [ "$(cat /tmp/python-packages-before)" != "$(cat /tmp/python-packages-after)" ]; then
    echo "--- the install changed which Pythons this machine has:"
    grep -vxF -f /tmp/python-packages-before /tmp/python-packages-after
    exit 13
fi

echo "--- interpreters present"
ls /usr/bin/python3* 2>&1 || true

# The libraries the desk is reached through, imported directly. Nothing else
# here opens them: the daemon below runs against a simulated desk and never
# touches Bluetooth, so a bundle missing that half would start, settle and be
# reported as running. The interpreter is read out of the installed launcher
# rather than written down again, so the two cannot disagree about which one
# the package runs -- and it is run the way the launcher runs it, isolated,
# which is also what puts the bundled libraries on its search path.
echo "--- the bundled Bluetooth libraries, on the interpreter the package ships"
bundled_python=$(sed -n 's/^PYTHON=//p' "$(command -v idasen-companiond)")
if [ -z "$bundled_python" ]; then
    echo "--- the installed launcher no longer states which interpreter it runs"
    exit 14
fi
"$bundled_python" -I -c \
    'from bleak import BleakScanner; from idasen import IdasenDesk' || exit 14

echo "--- version"
launcher_status=0
launcher_output=$(idasen-companiond --version 2>&1) || launcher_status=$?
echo "$launcher_output"

if [ "$launcher_status" -ne 0 ]; then
    # Matched against the launcher's own words for the one failure that is
    # not a defect of the package: an installation missing the interpreter it
    # was supposed to have brought.
    if echo "$launcher_output" | grep -q 'the Python it ships is missing'; then
        echo "--- the launcher declined, in its own words"
        exit 20
    fi
    exit 21
fi

if [ "$launcher_output" != "$EXPECTED_VERSION" ]; then
    echo "--- the installed package reports $launcher_output, not $EXPECTED_VERSION"
    exit 30
fi

echo "--- session bus"
install_session_bus || exit 12
command -v dbus-run-session >/dev/null 2>&1 || exit 12

echo "--- daemon"
# A simulated desk, always: there is no Bluetooth here, and a run that
# reached a real one would be driving somebody's furniture from a test.
dbus-run-session -- idasen-companiond \
    --mock-desk --config /tmp/idasen-companion-portability.toml \
    > /tmp/daemon.log 2>&1 &
daemon=$!

sleep "$SETTLE_SECONDS"

if ! kill -0 "$daemon" 2>/dev/null; then
    echo "--- the daemon exited during the first $SETTLE_SECONDS seconds"
    cat /tmp/daemon.log
    exit 40
fi

kill "$daemon" 2>/dev/null || true
wait "$daemon" 2>/dev/null || true
cat /tmp/daemon.log

grep -q 'MOCK desk' /tmp/daemon.log || exit 41

# The desk's statistics, written and then read back. This is the feature the
# bundled interpreter exists for: where a distribution splits the standard
# library, the database module the daemon keeps its statistics in lands in the
# half nothing this package declares would bring, so a machine could satisfy
# every dependency and still hold nothing that could record a minute of desk
# time. Running the daemon does not settle it -- the store is best-effort by
# design and turns each of its own failures into a no-op, so a check that calls
# it and looks at nothing passes exactly where the module is missing.
#
# So the store is required to open, and the numbers are required to come back:
# a known credit against a known state, one transition, both read out again and
# compared. Written to a throwaway path here rather than to a real data
# directory, with values that are nobody's desk time. Reported separately from
# the daemon so "it started and its statistics are dead" is its own answer.
echo "--- the desk's statistics, written and read back"
"$bundled_python" -I -B - <<'STATS_ROUND_TRIP' || exit 50
import sys
from datetime import date
from pathlib import Path

from idasen_companion.daemon.stats import Stats

CREDITED_STATE = "standing"
CREDITED_SECONDS = 1234.5
FROM_STATE, TO_STATE, TRIGGER = "sitting", "standing", "portability"

store = Stats(Path("/tmp/idasen-companion-portability-stats/stats.sqlite"),
              on_error=lambda reason: print("the store reported:", reason))
if not store.available:
    print("the statistics store did not open, so every call to it is a no-op")
    sys.exit(1)

today = date.today()
store.add_active_time(CREDITED_STATE, CREDITED_SECONDS, today)
store.record_transition(FROM_STATE, TO_STATE, TRIGGER, False)
totals = {state: seconds for _, state, seconds in store.daily_totals(today, today)}
transitions = store.recent_transitions(5)
store.close()

print("daily totals:", totals)
print("transitions:", transitions)

if totals.get(CREDITED_STATE) != CREDITED_SECONDS:
    print("the seconds credited to", CREDITED_STATE, "did not come back")
    sys.exit(1)
if len(transitions) != 1 or transitions[0][1:4] != (FROM_STATE, TO_STATE, TRIGGER):
    print("the transition written did not come back")
    sys.exit(1)
print("the statistics wrote and read back")
STATS_ROUND_TRIP

exit 0
IN_CONTAINER
}

main "$@"
