Name:           adjustor
Version:        REPLACE_VERSION
Release:        1%{?dist}
Summary:        Adjustor, a userspace program for managing the TDP of handheld devices.

License:        GPL-3.0-or-later
URL:            https://github.com/hhd-dev/adjustor
Source:        	https://pypi.python.org/packages/source/a/%{name}/%{name}-%{version}.tar.gz   

BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
BuildRequires:  python3-devel
BuildRequires:  python3-build
BuildRequires:  python3-installer
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel

Requires:       python3
Requires:       python3-rich
Requires:       python3-yaml
Requires:       python3-pyroute2

%description
Handheld Daemon is a project that aims to provide utilities for managing handheld devices. With features ranging from TDP controls, to controller remappings, and gamescope session management. This will be done through a plugin system and an HTTP(/d-bus?) daemon, which will expose the settings of the plugins in a UI agnostic way.

%prep
%autosetup -n %{name}-%{version}

%build
%{python3} -m build --wheel --no-isolation

%install
%{python3} -m installer --destdir="%{buildroot}" dist/*.whl

%files
%doc readme.md
%license LICENSE
%{_bindir}/%{name}*
%{python3_sitelib}/%{name}*