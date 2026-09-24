#!/usr/bin/env bash
# Build the five release assets through one checked-in interface. Format
# workflows call the corresponding selector; a maintainer runs --all.
set -euo pipefail

cd "$(dirname "$0")/.."

build_rpm=false
build_deb=false
build_flatpak=false
build_all=false
output=dist-release

while [ "$#" -gt 0 ]; do
    case "$1" in
        --all) build_all=true; build_rpm=true; build_deb=true; build_flatpak=true ;;
        --rpm) build_rpm=true ;;
        --deb) build_deb=true ;;
        --flatpak) build_flatpak=true ;;
        --output)
            shift
            [ "$#" -gt 0 ] || { echo "error: --output needs a directory" >&2; exit 2; }
            output=$1
            ;;
        *) echo "usage: $0 (--all|--rpm|--deb|--flatpak) [--output DIR]" >&2; exit 2 ;;
    esac
    shift
done

if ! $build_rpm && ! $build_deb && ! $build_flatpak; then
    echo "usage: $0 (--all|--rpm|--deb|--flatpak) [--output DIR]" >&2
    exit 2
fi

case "$output" in
    /*) ;;
    *) output="$PWD/$output" ;;
esac
mkdir -p "$output"

# The format-specific selectors run inside their CI build environments. The
# local all-in-one gate creates those same environments, then builds Flatpak
# with the host's installed runtime. Mount the output separately so an
# absolute directory outside the checkout works too.
if $build_all; then
    command -v podman >/dev/null || { echo "error: podman is required for --all" >&2; exit 3; }
    podman run --rm --security-opt label=disable \
        -v "$PWD:/workspace" -v "$output:/output" -w /workspace fedora:43 \
        bash -lc "dnf install -y rpm-build rpmdevtools python3-devel python3-pip python3-build python3-setuptools systemd-rpm-macros desktop-file-utils python3-pytest python3-pytest-asyncio /usr/bin/strip /usr/bin/objdump /usr/bin/dbus-run-session 'libGL.so.1()(64bit)' 'libEGL.so.1()(64bit)' 'libxkbcommon.so.0()(64bit)' 'libfontconfig.so.1()(64bit)' 'libfreetype.so.6()(64bit)' 'libdbus-1.so.3()(64bit)' && bash scripts/build-release-variants.sh --rpm --output /output"
    podman run --rm --security-opt label=disable \
        -e DEBIAN_FRONTEND=noninteractive \
        -v "$PWD:/workspace" -v "$output:/output" -w /workspace debian:13 \
        bash -lc "apt-get update && apt-get install -y --no-install-recommends build-essential debhelper dh-python python3-all pybuild-plugin-pyproject devscripts lintian debhelper-compat python3-setuptools python3-pytest python3-pytest-asyncio python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtdbus python3-pyside6.qtsvg qt6-translations-l10n python3-babel python3-tomlkit python3-yaml python3-dbus-fast python3-idasen python3-bleak && bash scripts/build-release-variants.sh --deb --output /output"
    bash scripts/build-release-variants.sh --flatpak --output "$output"
    echo "Built release assets in $output:"
    find "$output" -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
    exit 0
fi

version=$(.venv/bin/python -c \
    "import sys; sys.path.insert(0, 'src'); import idasen_companion; print(idasen_companion.__version__)" \
    2>/dev/null || python3 -c \
    "import sys; sys.path.insert(0, 'src'); import idasen_companion; print(idasen_companion.__version__)")

sdist_built=false
build_sdist() {
    # Never trust a same-version archive left by an earlier source state.
    # Release branches commonly change packaging without bumping the version;
    # reusing that archive would silently build yesterday's sources.
    if ! $sdist_built; then
        python3 -m build --sdist
        sdist_built=true
    fi
}

if $build_rpm; then
    command -v rpmbuild >/dev/null || { echo "error: rpmbuild is required for --rpm" >&2; exit 3; }
    build_sdist
    rpm_top=$(mktemp -d)
    trap 'rm -rf "${rpm_top:-}" "${deb_tree:-}"' EXIT
    mkdir -p "$rpm_top/SOURCES"
    cp "dist/idasen_companion-${version}.tar.gz" "$rpm_top/SOURCES/"
    scripts/fetch-bundled-runtime.sh "$rpm_top/SOURCES"
    # Build the smaller, stricter Qt-free variant first so a flavor-boundary
    # regression fails before spending time assembling the desktop payload.
    rpmbuild -bb --define "_topdir $rpm_top" \
        --define "release_flavor headless" \
        packaging/idasen-companion-bundled.spec
    rpmbuild -bb --define "_topdir $rpm_top" \
        packaging/idasen-companion-bundled.spec
    cp "$rpm_top"/RPMS/x86_64/idasen-companion-[0-9]*.rpm "$output/"
    cp "$rpm_top"/RPMS/x86_64/idasen-companion-headless-*.rpm "$output/"
fi

if $build_deb; then
    command -v dpkg-buildpackage >/dev/null || { echo "error: dpkg-buildpackage is required for --deb" >&2; exit 3; }
    deb_tree=$(mktemp -d)
    mkdir -p "$deb_tree/source"
    tar --exclude=.git --exclude=.release-build --exclude=dist-release \
        --exclude=dist --exclude=.venv -cf - . | tar -xf - -C "$deb_tree/source"
    (
        cd "$deb_tree/source"
        dpkg-buildpackage -us -uc -b
    )
    cp "$deb_tree"/idasen-companion_*.deb "$output/"
    cp "$deb_tree"/idasen-companion-headless_*.deb "$output/"
fi

if $build_flatpak; then
    command -v flatpak-builder >/dev/null || { echo "error: flatpak-builder is required for --flatpak" >&2; exit 3; }
    build_sdist
    flatpak_work=$(mktemp -d)
    trap 'rm -rf "${rpm_top:-}" "${deb_tree:-}" "${flatpak_work:-}"' EXIT
    flatpak-builder --force-clean --disable-cache --disable-rofiles-fuse \
        --state-dir="$flatpak_work/state" --repo="$flatpak_work/repo" \
        "$flatpak_work/build" \
        packaging/flatpak/io.github.extricator.IdasenCompanion.yaml
    flatpak build-bundle "$flatpak_work/repo" \
        "$output/idasen-companion-${version}.flatpak" \
        io.github.extricator.IdasenCompanion
fi

echo "Built release assets in $output:"
find "$output" -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
