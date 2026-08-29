# Self-contained distribution variant (GitHub Releases): the app, every Python
# library it needs — Qt included, trimmed to the modules it uses — and the
# interpreter that runs them, under one private directory. The package asks
# the machine for no Python at all, so it is correct on any RPM distribution
# rather than on the one release it was built against.
#
# For repo-based distribution (COPR), prefer the clean three-package set:
# idasen-companion.spec + python-bleak.spec + python-idasen.spec.

%global appdir %{_prefix}/lib/idasen-companion

# The Python runtime the package carries. Two lines state something and the
# rest is derived from them, so the interpreter's minor version is written
# once: the tree, the binary inside it that both entry points exec, and the
# directory every bundled library and the app itself install into.
%global bundled_runtime %{appdir}/python
%global bundled_minor 3.14
%global bundled_interpreter %{bundled_runtime}/bin/python%{bundled_minor}
%global bundled_libraries %{bundled_runtime}/lib/python%{bundled_minor}/site-packages

# ...and the interpreter that never ships. %%prep leaves a second, untrimmed
# extraction of the same tarball beside the sources, and it is the program
# that installs the wheels and the app into the tree above. It has to be a
# different tree from the one that ships, because the trim takes pip and
# setuptools out of that one. Written relative to the directory %%install runs
# in, which is where %%prep left it.
%global install_driver python/bin/python%{bundled_minor}

# A private copy of Qt must not advertise its sonames to the rest of the
# system: another package could otherwise resolve against libraries that live
# here to be upgraded on this app's schedule, not the distribution's.
%global __provides_exclude_from ^%{appdir}/.*$
# The other half of the same decision. With those provides gone, the closure's
# *internal* edges — the bundled libraries linking each other — would be
# generated as requirements nothing on the machine can satisfy. Everything
# external is deliberately left to be generated, and every one of those is a
# soname, so the package names no distribution anywhere.
%global __requires_exclude ^(libQt6.*|libpyside6.*|libshiboken6.*|libicu.*)\\.so.*$
# Nothing here is built from source, so there are no debug sources to package;
# left defined, the build dies on an empty source list rather than skipping it.
%global debug_package %{nil}
# All three build-root policies below would work against a package that
# carries its own interpreter: one writes bytecode caches tagged for the
# build host's CPython into a tree that runs a different one, the second
# rewrites the shebang of every script in that tree to name the build host's
# interpreter, and the third runs the build host's own strip over every ELF
# file in the tree regardless of what already decided whether that file
# should be stripped. The interpreter trim already makes that decision once,
# correctly, for the one binary that matters here -- a BOLT-rewritten
# interpreter left alone on purpose, because every strip implementation tried
# against it corrupts it -- and an automatic pass with no knowledge of that
# would strip the same binary again and undo it. Set to nothing rather than
# undefined: measured directly against this build, %%undefine on any of the
# last three left the platform's own definition still running, and only
# replacing it with an empty one took.
#
# The third one's reach is wider than its reason, and there is no narrowing it
# here: rpm walks the whole build root and offers no way to except one path,
# so switching it off spares every ELF file the package carries rather than
# only the interpreter. %%install therefore runs that pass itself, file by
# file and past the one binary it must not touch, and %%check refuses a tree
# where anything else still carries a symbol table.
%undefine __brp_python_bytecompile
%undefine __brp_mangle_shebangs
%global __brp_strip %{nil}
%global __brp_strip_comment_note %{nil}
%global __brp_strip_lto %{nil}
# The package format to write, stated rather than inherited. Both build hosts
# this project uses — the CI container and a contributor's own workstation —
# already produce this one by default, so it changes nothing on either; it is
# here for a host whose rpm defaults to the newer one, and for the day that
# default moves.
%global _rpmformat 4

Name:           idasen-companion
Version:        1.1.1
# No distribution tag. Its job is to order rebuilds of the same version for
# different distributions, and this package has none: it is built once and
# runs everywhere, so a tag here would stamp the build host's identity onto an
# artifact that has nothing to do with it.
Release:        1
Summary:        Automatic sit/stand companion for the IKEA Idåsen desk (self-contained build)
# The app itself, AND everything the package carries. Effective license of the
# *package contents*, which is what a distribution asks for here — not just
# the app's own terms. Four groups, in the order they appear: this app; the
# nine bundled distributions, each of which ships its own text; the interpreter
# and the C libraries compiled into it, none of which ships a text anywhere in
# its tarball; and last, parenthesised, PySide6's and Qt's, used under the LGPL
# arm whose text ships alongside the GPL one.
#
# The third group is the one bundling an interpreter added. Its terms are the
# ones the interpreter build's own metadata records for the components it links
# statically, cross-checked against the versions the shipped binary reports for
# each. Every term below has its text installed under %%license, several of
# them vendored from this repository because upstream ships none.
#
# The Tcl binding would add one more term and does not appear: the interpreter
# trim removes the module that would need it, and that removal is a recorded
# entry which fails the build if it ever stops resolving, so the omission is
# guarded rather than assumed.
License:        GPL-3.0-or-later AND MIT AND BSD-3-Clause AND PSF-2.0 AND Python-2.0 AND CNRI-Python AND Apache-2.0 AND OpenSSL AND X11 AND Sleepycat AND BSD-2-Clause AND 0BSD AND Zlib AND bzip2-1.0.6 AND (LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only)
URL:            https://github.com/extricator/idasen-companion
# setuptools normalizes the sdist name per PEP 625 (underscore)
Source0:        idasen_companion-%{version}.tar.gz
# Produced by scripts/fetch-bundled-runtime.sh, which pins every distribution
# in it. That is the one step of this build that needs the network; rpmbuild
# itself runs offline against the tarball.
Source1:        idasen-companion-wheels-%{version}.tar.gz
# The other half of the same arrangement: the interpreter the package carries,
# written by that same script under the name and at the checksum it pins.
Source2:        cpython-3.14.7+20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz

BuildRequires:  python3-devel
# Both trimmers run under the build host's interpreter and shell out to these
# two: the symbol table comes off the bundled interpreter with one, and Qt's
# dependency graph is walked with the other. Asked for by path, the same form
# the sonames below use, so neither names a distribution's package.
BuildRequires:  /usr/bin/strip
BuildRequires:  /usr/bin/objdump
BuildRequires:  systemd-rpm-macros
BuildRequires:  desktop-file-utils
# for %%check
BuildRequires:  python3-pytest
BuildRequires:  python3-pytest-asyncio
# ...and the session bus the daemon is started on down there, so that what is
# proven to run is the tree this build is about to package. Asked for by path
# like the two programs above, so this line names no distribution either.
BuildRequires:  /usr/bin/dbus-run-session
# What the bundled Qt links against at import time. Without them 20 GUI test
# modules fail at collection. Required by soname on purpose: it is what lets
# this spec state a build dependency without naming a distribution's package
# for it.
BuildRequires:  libGL.so.1()(64bit)
BuildRequires:  libEGL.so.1()(64bit)
BuildRequires:  libxkbcommon.so.0()(64bit)
BuildRequires:  libfontconfig.so.1()(64bit)
BuildRequires:  libfreetype.so.6()(64bit)
BuildRequires:  libdbus-1.so.3()(64bit)

# The package asks the machine for no interpreter at all: it carries its own.
# Everything else it needs is generated from the libraries it ships, and every
# one of those comes out as a soname.
#
# One soname left this list at the CPython 3.14 bump: libcrypt.so.1. The
# crypt extension no longer exists in CPython at 3.14, so nothing in the
# bundled interpreter links it any more, and one cross-distribution
# dependency this package used to carry is simply gone. Its reappearance in
# a future `rpm -qp --requires` would mean something in the bundle started
# linking it again, not a fix.
Requires:       bluez
Recommends:     (gnome-shell-extension-appindicator if gnome-shell)

# Bundled distributions, at the versions scripts/fetch-bundled-runtime.sh pins.
# Bump a line there and its line here together. The first line is the runtime
# the package carries, and it is here for the same reason as the nine below:
# this section is what a security scanner reads, and the largest bundled
# component in the package would otherwise be the one thing it cannot see.
Provides:       bundled(python3) = 3.14.7
Provides:       bundled(python3dist(pyside6-essentials)) = 6.11.1
Provides:       bundled(python3dist(shiboken6)) = 6.11.1
Provides:       bundled(python3dist(bleak)) = 3.0.2
Provides:       bundled(python3dist(idasen)) = 0.13.1
Provides:       bundled(python3dist(dbus-fast)) = 5.0.22
Provides:       bundled(python3dist(pyyaml)) = 6.0.3
Provides:       bundled(python3dist(tomlkit)) = 0.15.1
Provides:       bundled(python3dist(voluptuous)) = 0.16.0
Provides:       bundled(python3dist(typing-extensions)) = 4.16.0

%description
Idasen Companion automatically alternates an IKEA Idåsen desk between
sitting and standing positions based on your active time at the
computer. Background daemon (systemd user service, D-Bus API, journald
logging) plus a Qt 6 GUI with tray icon, live status, manual controls,
presets, scheduling, statistics and desktop notifications.

This is the self-contained build. It carries its own Python — the interpreter
and every library the app uses, Qt included — in a private directory, and both
entry points run it directly. Nothing it installs depends on which Python a
distribution ships or on which distribution it is, so the same package is
correct wherever those two things differ. What it does need from the system is
Bluetooth and the ordinary desktop libraries Qt links against, which are
requirements on sonames and resolve by themselves.

%prep
%autosetup -n idasen_companion-%{version} -a 1
# The interpreter, unpacked beside the sources as python/. This extraction is
# not the one that ships: %%install copies it into the build root and trims the
# copy, while this one stays whole precisely because the trim removes pip — it
# is the program that installs the wheels and the app. It is never packaged;
# %%files names %{appdir} and nothing under the build directory.
tar xzf %{SOURCE2}

%build
# Nothing to do here: the bundled libraries arrive as wheels, and the app's
# own wheel is built during %%install so it lands directly in the private
# directory rather than in the interpreter's own search path.

%install
mkdir -p %{buildroot}%{appdir}

# The interpreter the package carries: a copy of what %%prep unpacked, cut down
# before anything at all is installed into it. That order is a safety property
# rather than a preference — the trim's own removals reach into site-packages,
# and run the other way round they would be deleting from a directory that by
# then also holds the app and nine bundled libraries.
cp -a python %{buildroot}%{bundled_runtime}
%{python3} scripts/trim-cpython.py %{buildroot}%{bundled_runtime}

# The two paths everything below installs into or execs, proven to exist
# before either is used. This is what catches an interpreter bumped to a new
# minor without the macro above moving with it: the installs would otherwise
# all succeed, into a directory the shipped interpreter never looks at.
if [ ! -x %{buildroot}%{bundled_interpreter} ] || \
   [ ! -d %{buildroot}%{bundled_libraries} ]; then
    echo "error: the unpacked interpreter does not carry both of" >&2
    echo "    %{bundled_interpreter}" >&2
    echo "    %{bundled_libraries}" >&2
    echo "which is what a minor version moved in one place only looks like" >&2
    exit 1
fi

# Installed by the interpreter that will run them, never by the build host's.
# The wheel set is resolved for this exact CPython minor, and two of its wheels
# are built for it rather than for the stable ABI — a pip one minor away
# refuses those outright and the build stops here, which is why this is a
# question of whether the package builds at all rather than of tidiness.
%{install_driver} -m pip install --no-index --find-links wheels --no-deps \
    --no-warn-script-location --target %{buildroot}%{bundled_libraries} \
    wheels/*.whl
# Into the install driver's own site-packages, not the tree above -- no
# --target is the point. The interpreter asset stopped carrying anything that
# can build a wheel, and the app's own build below runs with isolation off, so
# whatever this copy makes importable here is the whole of what that build can
# reach. It is discarded with the rest of this tree; the assertion after the
# purge below is what proves that stayed true.
%{install_driver} -m pip install --no-index --find-links build-backend \
    --no-deps --no-warn-script-location build-backend/*.whl
%{install_driver} -m pip install --no-deps --no-build-isolation \
    --no-warn-script-location --target %{buildroot}%{bundled_libraries} .
# The console scripts pip generates carry the interpreter that ran it in a
# shebang, which is the one this package must not install. The launcher below
# replaces them.
rm -rf %{buildroot}%{bundled_libraries}/bin

# Extension modules built for a single CPython minor. They are dead weight on
# every other interpreter, and shipping one would put back exactly the lock
# this package exists to remove. Both libraries that ship them — the D-Bus
# and YAML ones — carry pure-Python siblings and fall back to them.
#
# Scoped to the installed libraries and never wider: one directory up sits the
# standard library's own lib-dynload, whose modules are named the same way and
# two of which this package is required to keep.
find %{buildroot}%{bundled_libraries} -name '*.cpython-*.so' -print -delete

# ...and prove it, because the purge above is a glob over a wheel set that
# grows. A new dependency shipping a version-tagged module would otherwise
# re-lock the package silently, with a green build and a package that works
# perfectly on the machine that built it.
tagged=$(find %{buildroot}%{bundled_libraries} -name '*.cpython-*.so')
if [ -n "$tagged" ]; then
    echo "$tagged" >&2
    echo "error: a module built for one CPython minor survived the purge" >&2
    exit 1
fi

# ...and prove the other install above stayed where it was put. That one
# names no --target at all, on purpose: this is what turns that omission into
# a build failure the day it stops being true, instead of a package that
# happens to be correct because nobody asked it to be.
escaped=$(find %{buildroot}%{bundled_libraries} -iname '*setuptools*')
if [ -n "$escaped" ]; then
    echo "$escaped" >&2
    echo "error: something meant only for the install driver reached the shipped tree" >&2
    exit 1
fi
# Everything else installed here must be a stable-ABI Python module or one of
# Qt's own libraries and plugins, which are not Python modules at all.
unexpected=$(find %{buildroot}%{bundled_libraries} -name '*.so*' \
    ! -name '*.abi3.so*' ! -path '%{buildroot}%{bundled_libraries}/PySide6/Qt/*')
if [ -n "$unexpected" ]; then
    echo "$unexpected" >&2
    echo "error: a shared object ships that is neither stable-ABI nor Qt's" >&2
    exit 1
fi

# Qt arrives whole and leaves as the modules the app reaches. See the script
# for why the set is computed rather than listed.
%{python3} scripts/trim-pyside6.py %{buildroot}%{bundled_libraries}

# ...and the strip rpm's own build-root policy would have run, which is
# switched off at the top of this file for the whole build root because it
# cannot be told to spare one path. Last of the steps that touch these files,
# so what it walks is every object the package is about to carry rather than
# whichever of them had arrived by some earlier line. See the script for how
# the one binary that must not be stripped is recognised -- by its own layout,
# never by its name.
bash scripts/strip-bundled-tree.sh %{buildroot}%{appdir}

# Bytecode for the whole private tree, compiled by the interpreter that will
# read it, once nothing is going to move in that tree again. Two separate
# reasons, and neither of them is size.
#
# The installer compiles what it installs and nothing compiled the standard
# library underneath it, so four fifths of the source here used to arrive with
# no cache at all — and this directory belongs to root once installed, so each
# of those files was compiled again on every process start and the result
# thrown away, for both entry points, forever. Nothing raises when that
# happens; there is only the cost.
#
# The caches are checked against the source they were compiled from rather
# than against its modification time, so what the package ships stops
# depending on the timestamps this build happened to see, and an unpack or a
# copy that moves one cannot silently invalidate the lot. Every file is
# rewritten rather than only the ones with no cache, since the installer's own
# are already there in the other form.
#
# The path recorded inside each cache is rewritten from the build root to the
# directory the package installs into, so a traceback on a user's machine
# names a file they have.
%{buildroot}%{bundled_interpreter} -I -B -m compileall -q -f \
    --invalidation-mode checked-hash \
    -s %{buildroot} -p / %{buildroot}%{bundled_runtime}

# One launcher, installed once per entry point. Each is given the entry point
# it starts and the absolute path of the interpreter it execs — the one that
# ships, not the one that ran pip above; see
# packaging/idasen-companion-launcher.sh for why neither can be a generated
# console script. The interpreter is substituted with a delimiter that is not
# a slash, because what replaces it is a path.
install -Dm755 packaging/idasen-companion-launcher.sh \
    %{buildroot}%{_bindir}/idasen-companiond
sed -i -e 's/@ENTRY@/idasen_companion.daemon.main/' \
       -e 's|@PYTHON@|%{bundled_interpreter}|' \
    %{buildroot}%{_bindir}/idasen-companiond
install -Dm755 packaging/idasen-companion-launcher.sh \
    %{buildroot}%{_bindir}/idasen-companion
sed -i -e 's/@ENTRY@/idasen_companion.gui.main/' \
       -e 's|@PYTHON@|%{bundled_interpreter}|' \
    %{buildroot}%{_bindir}/idasen-companion

# Bundling obliges us to ship the bundled code's license texts too. Most
# wheels carry theirs under one of two conventional names, so copy each out
# under a name of its own — %%license flattens everything into one directory
# and same-named files would collide.
for info in %{buildroot}%{bundled_libraries}/*.dist-info; do
    # Directory name is the distribution and its version; drop the version.
    # Written as an edit rather than a shell suffix trim because the operator
    # that would do that has a second meaning inside a spec file.
    dist=$(basename "$info" .dist-info | sed 's/-[^-]*$//')
    for candidate in "$info"/licenses/LICENSE* "$info"/licenses/COPYING* \
                     "$info"/LICENSE* "$info"/COPYING*; do
        if [ -f "$candidate" ]; then
            cp "$candidate" "LICENSE.$dist"
            break
        fi
    done
done
# The texts that have to come from this repository, because the thing they
# cover ships without one. Qt's and PySide6's wheels carry no license file at
# all — neither a licenses directory nor a plain one — and neither does the
# interpreter tarball for any of the C libraries compiled into it. Copied as a
# directory rather than named one by one, since %%files names each of them: a
# text that stops being vendored fails the build there instead of quietly
# leaving a declared term with nothing behind it.
for text in packaging/licenses/*.txt; do
    cp "$text" "$(basename "$text")"
done

# The interpreter's own text, which is the one thing its tarball does ship.
# Taken from the extraction %%prep left beside the sources rather than from the
# build root: the trim runs over the build-root copy, and hanging a license
# install off the internals of a delete is how it silently stops happening.
cp python/lib/python%{bundled_minor}/LICENSE.txt LICENSE.cpython

install -Dm644 data/idasen-companion.service \
    %{buildroot}%{_userunitdir}/idasen-companion.service
install -Dm644 data/io.github.extricator.IdasenCompanion.desktop \
    %{buildroot}%{_datadir}/applications/io.github.extricator.IdasenCompanion.desktop
install -Dm644 data/icons/io.github.extricator.IdasenCompanion.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion.svg
install -Dm644 data/icons/io.github.extricator.IdasenCompanion-symbolic.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion-symbolic.svg
install -Dm644 data/io.github.extricator.IdasenCompanion.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/io.github.extricator.IdasenCompanion.metainfo.xml

%check
desktop-file-validate \
    %{buildroot}%{_datadir}/applications/io.github.extricator.IdasenCompanion.desktop
# What the tree about to be packaged links, and how new a C library it asks
# for. Both were measured once and then designed around — the shared copy of
# libpython is absent because nothing here references it, and the oldest
# distribution line this package reaches is the one its symbol versions have to
# stay inside — and a release of Qt or of CPython is enough to end either,
# without a line of this repository changing. See the script.
bash scripts/verify-bundled-elf.sh %{buildroot}%{appdir}
# Guard against a silently shrinking %%check: 14 GUI test modules skip
# themselves when Qt is missing, and the suite still goes green having
# verified 72%% of itself. The subject moved with this build — it is the
# bundled Qt that has to import, not the machine's.
#
# On the interpreter that ships, and isolated, for the same reason the daemon
# below is: a build host's Python importing out of this tree answers a question
# nobody is asking, since no user ever runs that combination. It also *writes*
# there. Its own site directory carries a path configuration file that shims a
# module by name at every startup, and a search path pointed here outranks the
# host's own copy — so merely starting it against this tree compiled three of
# these modules for an interpreter the package does not carry, and the build
# packaged them.
QT_QPA_PLATFORM=offscreen %{buildroot}%{bundled_interpreter} -I -B \
    -c "from PySide6 import QtCore, QtGui, QtWidgets, QtDBus"
# Importing is not the interesting half. The two experiments this package's
# design rests on were run against different trees — Qt against an untrimmed
# interpreter, the standard library against a trimmed one that had no Qt in it
# — so the combination that actually ships is the one thing neither of them
# covered. This starts the daemon out of the build root, on the interpreter the
# package carries, the way the installed launcher will start it.
#
# A simulated desk, always: there is no Bluetooth in a build root, and a build
# that reached a real one would be driving somebody's furniture. The two
# directories the app writes to are pointed inside the build directory as well,
# so a package build leaves nothing behind in the builder's own home.
#
# Bytecode caching is off for the same reason the interpreter trim's own proof
# turns it off: without that, the daemon's imports write the standard library's
# caches into the very tree this is verifying, and the build then packages
# them. A check that changes its subject is measuring something else.
smoke=$(pwd)/check-daemon
rm -rf "$smoke"
mkdir -p "$smoke/data" "$smoke/config"
# setsid, and then a *group* kill, because the thing started here is
# dbus-run-session and the thing under test is the daemon it spawns. $! names
# the wrapper only, so killing it leaves the daemon orphaned and running —
# every build leaking one, silently, for as long as the machine is up. Three
# were found alive on a developer's workstation, the oldest three days old.
# setsid makes the wrapper a session and process-group leader (it does not
# fork here: a background job in a non-interactive shell is not already a
# group leader), so its PID is also the group id, and the negative kill below
# reaches the daemon and the bus with it.
QT_QPA_PLATFORM=offscreen \
XDG_DATA_HOME="$smoke/data" XDG_CONFIG_HOME="$smoke/config" \
    setsid dbus-run-session -- %{buildroot}%{bundled_interpreter} -I -B \
        -m idasen_companion.daemon.main --mock-desk \
        --config "$smoke/daemon.toml" > "$smoke/daemon.log" 2>&1 &
daemon=$!
# Long enough to reach the first automation tick and the first status
# broadcast, which is where a tree that imports but cannot run falls over.
sleep 10
if ! kill -0 "$daemon" 2>/dev/null; then
    cat "$smoke/daemon.log" >&2
    echo "error: the daemon did not survive its first seconds, so this build" >&2
    echo "is about to package a tree that does not run" >&2
    kill -- -"$daemon" 2>/dev/null || true
    exit 40
fi
kill -- -"$daemon" 2>/dev/null || true
wait "$daemon" 2>/dev/null || true
cat "$smoke/daemon.log"
# Secondary, and deliberately not the gate: what decides the outcome above is
# the process still being there. This says which path it took to get there —
# a daemon that reached a real desk would be a different failure entirely.
grep -q 'MOCK desk' "$smoke/daemon.log" || exit 41

# Run the suite against the tree that actually ships, trimmed Qt included,
# rather than against a copy installed elsewhere plus the machine's own Qt —
# and on the interpreter that ships, so that what a green suite reports on is
# the pair the package installs rather than half of it under the build host's
# Python.
#
# The test framework is the one thing here that cannot come from the package:
# nothing in the payload is a test dependency, and the build is offline, so it
# is the build host's. It is handed over as a *trailing* search path under
# isolation — appended after the interpreter's own directories, never in front
# of them through the environment, which is where a host copy of a bundled
# library would quietly become the one the suite verified. The consequence
# worth knowing: this build now needs a host test framework the bundled minor
# can import, and the day that stops being true the build says so.
host_test_framework=$(%{python3} -c \
    'import os, pytest; print(os.path.dirname(os.path.dirname(pytest.__file__)))')
QT_QPA_PLATFORM=offscreen HOST_TEST_FRAMEWORK="$host_test_framework" \
    %{buildroot}%{bundled_interpreter} -I -B -c \
    'import os, sys; sys.path.append(os.environ["HOST_TEST_FRAMEWORK"]); import pytest; sys.exit(pytest.console_main())' \
    -q

# Last of everything, because every step above runs *out of* the tree it
# examines and this is what says none of them wrote there. What it holds the
# payload to is that its bytecode is the shipped interpreter's, that there is
# some for every source file, and that each cache is checked against that file
# rather than against a clock. See the script for what each of those costs
# when it stops being true.
#
# The tag is asked of the interpreter in the build root rather than written
# down beside the minor version above: this then reports on the interpreter
# that ships even when somebody has moved that version in one place only,
# which is precisely when a check comparing two constants would agree with
# itself and say nothing.
bytecode_tag=$(%{buildroot}%{bundled_interpreter} -I -B -c \
    'import sys; print(sys.implementation.cache_tag)')
bash scripts/verify-bundled-bytecode.sh %{buildroot}%{appdir} "$bytecode_tag"

# No icon-cache scriptlets: hicolor-icon-theme ships transfiletriggerin and
# transfiletriggerpostun on /usr/share/icons/hicolor that run
# gtk-update-icon-cache for us. Doing it here as well is obsolete per current
# Fedora packaging guidelines and would draw a review comment.
%post
%systemd_user_post idasen-companion.service

%preun
%systemd_user_preun idasen-companion.service

%postun
%systemd_user_postun_with_restart idasen-companion.service

%files
# Named one by one rather than globbed: a wheel that stops shipping its
# license text fails the build here instead of quietly dropping it.
%license LICENSE LICENSE.LGPL-3.0.txt LICENSE.bleak LICENSE.dbus_fast
%license LICENSE.idasen LICENSE.pyyaml LICENSE.tomlkit LICENSE.voluptuous
%license LICENSE.typing_extensions LICENSE.cpython
%license LICENSE.Apache-2.0.txt LICENSE.OpenSSL.txt LICENSE.X11.txt
%license LICENSE.Sleepycat.txt LICENSE.BSD-2-Clause.txt LICENSE.0BSD.txt
%license LICENSE.Zlib.txt LICENSE.bzip2-1.0.6.txt
%doc README.md
%{_bindir}/idasen-companion
%{_bindir}/idasen-companiond
%{appdir}/
%{_userunitdir}/idasen-companion.service
%{_datadir}/applications/io.github.extricator.IdasenCompanion.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion.svg
%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion-symbolic.svg
%{_datadir}/metainfo/io.github.extricator.IdasenCompanion.metainfo.xml

%changelog
* Thu Aug 20 2026 extricator <extricator@users.noreply.github.com> - 1.1.1-1
- Label the Statistics range slider's preset ticks through the shared
  vocabulary, so they no longer print the raw lowercase preset key
  untranslated.
- Translate the daily chart's tooltip, which shipped English in every
  language.
- Render every user-facing string as one whole catalog entry with named
  substitutions instead of joining translated fragments, so a translation
  can reorder what English fixed in place.
- Merge eight concepts that each reached the Qt catalog twice into the one
  shared entry, and gate all three rules in the test suite.

* Tue Aug 18 2026 extricator <extricator@users.noreply.github.com> - 1.1.0-1
- Ship a self-contained RPM that carries its own Python and Qt and installs on
  any RPM-based distribution rather than a single Fedora release.
- Follow the desktop's theme more closely throughout the window, including a
  switch between light and dark while the app is open.
- Group the activity log's entries under dated separators, and redraw the log
  in one pass instead of row by row.

* Fri Aug 14 2026 extricator <extricator@users.noreply.github.com> - 1.0.2-1
- Release the desk's Bluetooth link before the machine sleeps, under a logind
  delay lock, and reconcile it against BlueZ on resume. A suspend entered
  while the link was up used to hold the desk's one connection slot for the
  whole sleep.
- Bound the Bluetooth disconnect so a stalled connection can no longer block
  every later desk operation for the life of the daemon.
- Point the AppStream screenshot URLs at the default branch instead of the
  release tag.

* Thu Aug 13 2026 extricator <extricator@users.noreply.github.com> - 1.0.1-1
- Fix the AppStream screenshot URLs, which named a tag that does not carry
  the image files, leaving software centres with nothing to show.
- Replace the three functional screenshots with five composed for a software
  centre, one per page of the window.
- Restructure the README and move the package build instructions into
  CONTRIBUTING.md.
- End each release body with a comparison against the previous release.

* Sun Aug 09 2026 extricator <extricator@users.noreply.github.com> - 1.0.0-1
- First public release: active-time sit/stand automation with presence
  gating, presets and manual control, statistics, the tray application and
  its D-Bus API, and English/Spanish localisation.

* Thu Aug 06 2026 extricator <extricator@users.noreply.github.com> - 0.2.0-1
- Pre-release review pass. Correctness: a backward clock step no longer
  corrupts the cycle or writes negative statistics; a malformed preset raises
  ConfigError instead of killing a running daemon; a failed idasen-CLI import
  no longer wedges the first start; a statistics failure no longer stops desk
  automation; the BLE link is released before any shutdown bookkeeping; Stop
  no longer leaves move state stale (which made the next same-direction
  gesture reverse the desk).
- The automation tick is serialized against manual desk operations, so
  pressing Sit mid-move is no longer undone by the interruption policy.
- Desk1.Moving is now reported during automation moves, not just manual ones.
- The first-run wizard opens on a fresh install, where the daemon is present
  but not yet running.
- Failed daemon commands now reach the user instead of being discarded.
- Statistics page, preset names, dates and times are localized; eight daemon
  error messages are translatable GUI-side.
- The GUI binary has a real CLI: --help and --version no longer open a window.
- Packaging: the COPR spec installs the symbolic tray icon; %%check can no
  longer silently skip the GUI tests.

* Mon Jul 20 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-7
- Complete the Spanish (es) translation: all 202 GUI strings now translated
  (previously ~half), including the tray tooltip, setup wizard, and settings.

* Mon Jul 20 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-6
- Translate the desk position word (sitting/standing) in the tray tooltip and
  Overview heading, which previously stayed English in other locales.
- Settings: Save is a plain button (was accent-filled) to match Revert.

* Mon Jul 20 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-5
- Add a Language setting (Settings > General): choose System default, English,
  or a shipped translation. Honored by both the GUI and the daemon's
  notifications (persisted as [ui] language); applies on GUI relaunch.

* Mon Jul 20 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-4
- Internationalization: GUI strings are translatable via Qt (.qm catalogs)
  and daemon desktop notifications via gettext (.mo catalogs); both ship
  inside the package and load for the system locale. Spanish (es) included.
- Startup now adopts the desk's real position silently (no phantom
  "external" transition recorded on restart).

* Mon Jul 20 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-2
- Automation controls (pause/resume/skip/snooze) and config reload now emit
  StatusChanged/ProgressChanged immediately, so the window and tray update
  within a D-Bus round-trip instead of waiting for the next 60s tick.
- GUI: split main_window into a gui/pages/ package (no behavior change).

* Sat Jul 18 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-1
- Initial release (bundled single-RPM variant)
