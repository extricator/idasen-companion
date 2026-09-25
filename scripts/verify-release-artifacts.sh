#!/usr/bin/env bash
# Validate and smoke-test the complete five-asset release set.
set -euo pipefail

cd "$(dirname "$0")/.."
[ "$#" -eq 1 ] || { echo "usage: $0 DIR" >&2; exit 2; }
artifact_dir=$1
[ -d "$artifact_dir" ] || { echo "error: no artifact directory: $artifact_dir" >&2; exit 2; }
case "$artifact_dir" in /*) ;; *) artifact_dir="$PWD/$artifact_dir" ;; esac

for command in podman flatpak; do
    command -v "$command" >/dev/null || {
        echo "error: $command is required for release verification" >&2
        exit 3
    }
done

shopt -s nullglob
full_rpms=("$artifact_dir"/idasen-companion-[0-9]*.rpm)
headless_rpms=("$artifact_dir"/idasen-companion-headless-*.rpm)
full_debs=("$artifact_dir"/idasen-companion_[0-9]*.deb)
headless_debs=("$artifact_dir"/idasen-companion-headless_*.deb)
flatpaks=("$artifact_dir"/idasen-companion-[0-9]*.flatpak)

for count in "${#full_rpms[@]}" "${#headless_rpms[@]}" \
             "${#full_debs[@]}" "${#headless_debs[@]}" "${#flatpaks[@]}"; do
    [ "$count" -eq 1 ] || {
        echo "error: release directory must contain exactly one of each of five assets" >&2
        find "$artifact_dir" -maxdepth 1 -type f -printf '%f\n' | sort >&2
        exit 4
    }
done
[ "$(find "$artifact_dir" -maxdepth 1 -type f | wc -l)" -eq 5 ] || {
    echo "error: release directory contains files outside the five-asset contract" >&2
    exit 4
}

full_rpm=${full_rpms[0]}; headless_rpm=${headless_rpms[0]}
full_deb=${full_debs[0]}; headless_deb=${headless_debs[0]}
flatpak_bundle=${flatpaks[0]}
version=$(python3 -c \
    "import sys; sys.path.insert(0, 'src'); import idasen_companion; print(idasen_companion.__version__)")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cat >"$work/native-smoke.sh" <<'NATIVE_SMOKE'
#!/usr/bin/env bash
set -euo pipefail
kind=$1
flavor=$2
package=$3
expected_version=$4

if [ "$kind" = rpm ]; then
    dnf install -y "$package" /usr/bin/dbus-run-session >/dev/null
    package_name=$(rpm -qp --qf '%{NAME}' "$package")
    conflict=$(rpm -qp --qf '[%{CONFLICTNAME}\n]' "$package")
    requirements=$(rpm -qpR "$package")
    files=$(rpm -qlp "$package")
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "$package" dbus-daemon >/dev/null
    package_name=$(dpkg-deb -f "$package" Package)
    conflict=$(dpkg-deb -f "$package" Conflicts)
    requirements=$(dpkg-deb -f "$package" Depends)
    files=$(dpkg-deb -c "$package")
fi

if [ "$flavor" = full ]; then
    [ "$package_name" = idasen-companion ]
    grep -Fw idasen-companion-headless <<<"$conflict" >/dev/null
    command -v idasen-companion >/dev/null
    QT_QPA_PLATFORM=offscreen idasen-companion --version | grep -F "$expected_version"
else
    [ "$package_name" = idasen-companion-headless ]
    grep -Fw idasen-companion <<<"$conflict" >/dev/null
    ! command -v idasen-companion >/dev/null
    ! grep -Eiq '(/gui/|pyside|shiboken|/qt6|\.desktop|/icons/|metainfo)' <<<"$files"
    ! grep -Eiq '(pyside|shiboken|libqt6|qt6-)' <<<"$requirements"
    python_command=python3
    if [ "$kind" = rpm ]; then
        python_command=$(sed -n 's/^PYTHON=//p' "$(command -v idasen-companiond)")
    fi
    "$python_command" -I -B -c \
        "import idasen_companion.cli, idasen_companion.daemon.main, sys; assert not any(n.startswith(('PySide6', 'shiboken6')) or n == 'idasen_companion.gui' for n in sys.modules)"
fi

grep -F '/idasen_companion.mo' <<<"$files" >/dev/null
grep -F '/usr/lib/systemd/user/idasen-companion.service' <<<"$files" >/dev/null
idasen-companion-cli --version | grep -F "$expected_version"
idasen-companion-cli --help >/dev/null
idasen-companiond --help >/dev/null

smoke=$(mktemp -d)
dbus-run-session -- bash -c '
    set -e
    idasen-companiond --mock-desk --config "$1/daemon.toml" >"$1/daemon.log" 2>&1 &
    daemon=$!
    trap "kill $daemon 2>/dev/null || true; wait $daemon 2>/dev/null || true" EXIT
    for _ in $(seq 1 20); do
        if idasen-companion-cli status >"$1/status.log" 2>&1; then
            cat "$1/status.log"
            exit 0
        fi
        sleep 0.5
    done
    cat "$1/daemon.log" >&2
    cat "$1/status.log" >&2
    exit 1
' _ "$smoke"
NATIVE_SMOKE
chmod +x "$work/native-smoke.sh"

run_native() {
    local image=$1 kind=$2 flavor=$3 package=$4
    echo "===== $kind $flavor: $(basename "$package") ====="
    podman run --rm --security-opt label=disable \
        -v "$artifact_dir:/artifacts:ro" \
        -v "$work/native-smoke.sh:/native-smoke.sh:ro" \
        "$image" bash /native-smoke.sh "$kind" "$flavor" \
        "/artifacts/$(basename "$package")" "$version"
}

run_native fedora:43 rpm headless "$headless_rpm"
run_native fedora:43 rpm full "$full_rpm"
run_native debian:13 deb headless "$headless_deb"
run_native debian:13 deb full "$full_deb"

echo "===== flatpak full: $(basename "$flatpak_bundle") ====="
flatpak_dir="$work/flatpak-user"
mkdir -p "$flatpak_dir"
XDG_DATA_HOME="$flatpak_dir" flatpak --user install --noninteractive --bundle "$flatpak_bundle"
XDG_DATA_HOME="$flatpak_dir" flatpak --user info io.github.extricator.IdasenCompanion \
    | grep -F "Version: $version"
XDG_DATA_HOME="$flatpak_dir" flatpak --user run \
    --command=idasen-companion-cli io.github.extricator.IdasenCompanion --help >/dev/null
XDG_DATA_HOME="$flatpak_dir" QT_QPA_PLATFORM=offscreen flatpak --user run \
    io.github.extricator.IdasenCompanion --version | grep -F "$version"

for artifact in "$full_rpm" "$headless_rpm" "$full_deb" "$headless_deb" "$flatpak_bundle"; do
    [ -s "$artifact" ] || { echo "error: empty artifact: $artifact" >&2; exit 6; }
    printf '%s %s bytes\n' "$(basename "$artifact")" "$(stat -c %s "$artifact")"
done

echo "all five release artifacts passed clean-install, payload, dependency, and runtime smoke checks"
