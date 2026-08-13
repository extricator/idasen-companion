# Dependency package for idasen-companion (bleak is not in Fedora repos).
# Pure Python on Linux; the BlueZ D-Bus backend uses dbus-fast, which IS
# packaged in Fedora.
%global pypi_name bleak

Name:           python-%{pypi_name}
Version:        3.0.2
Release:        1%{?dist}
Summary:        Bluetooth Low Energy platform-agnostic client for Python
License:        MIT
URL:            https://github.com/hbldh/bleak
Source0:        %{pypi_source %{pypi_name}}
BuildArch:      noarch
BuildRequires:  python3-devel

%global _description %{expand:
Bleak is a GATT client software capable of connecting to BLE devices
acting as GATT servers. On Linux it talks to BlueZ over D-Bus.}

%description %_description

%package -n python3-%{pypi_name}
Summary:        %{summary}
Requires:       python3-dbus-fast

%description -n python3-%{pypi_name} %_description

%prep
%autosetup -n %{pypi_name}-%{version}
# Upstream pins uv_build>=0.10.9,<0.11.0; Fedora ships 0.11+. The upper
# bound is precautionary — loosen it.
sed -i 's/uv_build>=[0-9.]*,<[0-9.]*/uv_build>=0.10/' pyproject.toml

%generate_buildrequires
# -R: runtime deps (dbus-fast) aren't needed to build a pure-Python wheel.
%pyproject_buildrequires -R

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files %{pypi_name}

%files -n python3-%{pypi_name} -f %{pyproject_files}

%changelog
* Sat Jul 18 2026 extricator <extricator@users.noreply.github.com> - 3.0.2-1
- Initial package for the idasen-companion COPR
