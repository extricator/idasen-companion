# Dependency package for idasen-companion (idasen is not in Fedora repos).
%global pypi_name idasen

Name:           python-%{pypi_name}
Version:        0.13.1
Release:        1%{?dist}
Summary:        IKEA IDÅSEN desk API and CLI
License:        MIT
URL:            https://github.com/newAM/idasen
Source0:        %{pypi_source %{pypi_name}}
BuildArch:      noarch
BuildRequires:  python3-devel

%global _description %{expand:
Python API and command line interface for the IKEA IDÅSEN standing
desk, controlling it over Bluetooth Low Energy via bleak.}

%description %_description

%package -n python3-%{pypi_name}
Summary:        %{summary}
Requires:       python3-bleak
Requires:       python3-pyyaml
Requires:       python3-voluptuous

%description -n python3-%{pypi_name} %_description

%prep
%autosetup -n %{pypi_name}-%{version}

%generate_buildrequires
# -R: runtime deps aren't needed to build; lets this package build before
# python-bleak is installed (local builds and COPR chain builds).
%pyproject_buildrequires -R

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files %{pypi_name}

%files -n python3-%{pypi_name} -f %{pyproject_files}
%{_bindir}/idasen

%changelog
* Sat Jul 18 2026 extricator <extricator@users.noreply.github.com> - 0.13.1-1
- Initial package for the idasen-companion COPR
