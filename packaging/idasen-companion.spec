Name:           idasen-companion
Version:        1.0.2
Release:        1%{?dist}
Summary:        Automatic sit/stand companion for the IKEA Idåsen desk
# bleak/idasen are separate RPMs here (see python-*.spec), so this is the
# app's own license only — unlike the bundled variant, which vendors them.
License:        GPL-3.0-or-later
URL:            https://github.com/extricator/idasen-companion
# setuptools normalizes the sdist name per PEP 625 (underscore)
Source0:        idasen_companion-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
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
Requires:       python3-idasen
Requires:       python3-bleak
Requires:       python3-pyyaml
Requires:       python3-tomlkit
Requires:       bluez
# The tray icon on GNOME needs a StatusNotifier host:
Recommends:     (gnome-shell-extension-appindicator if gnome-shell)

%description
Idasen Companion automatically alternates an IKEA Idåsen desk between
sitting and standing positions based on your active time at the
computer. It ships a background daemon (systemd user service, D-Bus
API, journald logging) and a Qt 6 GUI with a system tray icon, live
status, manual controls, presets, scheduling, statistics and desktop
notifications. Works on GNOME and KDE Plasma, X11 and Wayland.

%prep
%autosetup -n idasen_companion-%{version}

%generate_buildrequires
# -R: runtime deps (bleak, idasen, ...) aren't needed to build or run the
# test suite, which uses fakes — so building doesn't require the dependency
# RPMs to be installed first.
%pyproject_buildrequires -R

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files idasen_companion

install -Dm644 data/idasen-companion.service \
    %{buildroot}%{_userunitdir}/idasen-companion.service
install -Dm644 data/io.github.extricator.IdasenCompanion.desktop \
    %{buildroot}%{_datadir}/applications/io.github.extricator.IdasenCompanion.desktop
install -Dm644 data/icons/io.github.extricator.IdasenCompanion.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion.svg
%{_datadir}/icons/hicolor/scalable/apps/io.github.extricator.IdasenCompanion-symbolic.svg
# The tray asks for APP_ID-symbolic by name (gui/main.py); without this the
# panel falls back to the 64x64 full-colour launcher icon.
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

%post
%systemd_user_post idasen-companion.service

%preun
%systemd_user_preun idasen-companion.service

%postun
%systemd_user_postun_with_restart idasen-companion.service

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/idasen-companion
%{_bindir}/idasen-companiond
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

* Sat Jul 18 2026 extricator <extricator@users.noreply.github.com> - 0.1.0-1
- Initial release
