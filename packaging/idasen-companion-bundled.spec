# Single-file distribution variant (e.g. GitHub Releases): bundles the two
# Python libraries missing from Fedora (bleak, idasen) inside the app RPM
# under /usr/lib/idasen-companion/vendor. All other dependencies resolve
# from the regular Fedora repos.
#
# For repo-based distribution (COPR), prefer the clean three-package set:
# idasen-companion.spec + python-bleak.spec + python-idasen.spec.

%global bleak_version 3.0.2
%global idasen_version 0.13.1

# The wheel metadata declares bleak/idasen; they're bundled, not RPM deps.
%global __requires_exclude python3.*dist\\((bleak|idasen)\\)

Name:           idasen-companion
Version:        1.0.2
Release:        1%{?dist}
Summary:        Automatic sit/stand companion for the IKEA Idåsen desk (bundled build)
# The app itself, AND the two MIT libraries vendored in below. Effective
# license of the *package contents*, which is what Fedora asks for here —
# not just the app's own terms.
License:        GPL-3.0-or-later AND MIT
URL:            https://github.com/extricator/idasen-companion
# setuptools normalizes the sdist name per PEP 625 (underscore)
Source0:        idasen_companion-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/source/b/bleak/bleak-%{bleak_version}.tar.gz
Source2:        https://files.pythonhosted.org/packages/source/i/idasen/idasen-%{idasen_version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  python3-uv-build
BuildRequires:  systemd-rpm-macros
BuildRequires:  desktop-file-utils
# for %%check
BuildRequires:  python3-pytest
BuildRequires:  python3-pytest-asyncio
BuildRequires:  python3-tomlkit
BuildRequires:  python3-pyyaml
BuildRequires:  python3-dbus-fast
# PySide6 is a runtime Requires, not a build input — but without it here the
# 14 GUI test modules importorskip themselves and %%check silently verifies
# only 72%% of the suite while still going green. It is already installed on
# any machine that can run the result.
BuildRequires:  python3-pyside6

Requires:       python3-pyside6
Requires:       python3-dbus-fast
Requires:       python3-pyyaml
Requires:       python3-tomlkit
Requires:       python3-voluptuous
Requires:       bluez
Recommends:     (gnome-shell-extension-appindicator if gnome-shell)

# The vendored copies live in a private directory and are prepended to the
# app's own sys.path, so they coexist safely with any python3-bleak/-idasen
# RPMs or pip installs the user may have — no Conflicts needed.
Provides:       bundled(python3dist(bleak)) = %{bleak_version}
Provides:       bundled(python3dist(idasen)) = %{idasen_version}

%description
Idasen Companion automatically alternates an IKEA Idåsen desk between
sitting and standing positions based on your active time at the
computer. Background daemon (systemd user service, D-Bus API, journald
logging) plus a Qt 6 GUI with tray icon, live status, manual controls,
presets, scheduling, statistics and desktop notifications.

This is the self-contained single-RPM build: the bleak and idasen
Python libraries (not packaged in Fedora) are bundled privately under
/usr/lib/idasen-companion/vendor.

%prep
# %%autosetup honors only a single -a; extract the second source manually.
%autosetup -n idasen_companion-%{version} -a 1
tar xzf %{SOURCE2}
# Upstream pins uv_build>=0.10.9,<0.11.0; Fedora ships 0.11+. The upper
# bound is precautionary — loosen it.
sed -i 's/uv_build>=[0-9.]*,<[0-9.]*/uv_build>=0.10/' bleak-%{bleak_version}/pyproject.toml

%generate_buildrequires
%pyproject_buildrequires -R

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files idasen_companion

# Vendor the two libraries, built from their sdists.
%{python3} -m pip install --no-deps --no-build-isolation \
    --no-warn-script-location \
    --target %{buildroot}%{_prefix}/lib/idasen-companion/vendor \
    ./bleak-%{bleak_version} ./idasen-%{idasen_version}
# Drop console scripts of the vendored libs; only the library code is used.
rm -rf %{buildroot}%{_prefix}/lib/idasen-companion/vendor/bin

# Bundling obliges us to ship the bundled code's license texts too. Both
# sdists name theirs plain `LICENSE`, so copy them out under distinct names —
# %%license flattens everything into one directory and would otherwise collide.
cp bleak-%{bleak_version}/LICENSE LICENSE.bleak
cp idasen-%{idasen_version}/LICENSE LICENSE.idasen

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
# Guard the BuildRequires above: without PySide6 the GUI tests skip rather
# than fail, so a green %%check would mean much less than it appears to.
%{python3} -c "import PySide6"
%pytest -q

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

%files -f %{pyproject_files}
%license LICENSE LICENSE.bleak LICENSE.idasen
%doc README.md
%{_bindir}/idasen-companion
%{_bindir}/idasen-companiond
%{_prefix}/lib/idasen-companion/
%{_userunitdir}/idasen-companion.service
%{_datadir}/applications/io.github.extricator.IdasenCompanion.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion.svg
%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion-symbolic.svg
%{_datadir}/metainfo/io.github.extricator.IdasenCompanion.metainfo.xml

%changelog
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
