Name:           hhd
Version:        1.0.2
Release:        1%{?dist}
Summary:        Handheld Daemon, a tool for configuring handheld devices.

License:        MIT
URL:            https://github.com/hhd-dev/hhd
Source:        	https://pypi.python.org/packages/source/h/%{name}/%{name}-%{version}.tar.gz   

BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
BuildRequires:  python3-devel
BuildRequires:  python3-build
BuildRequires:  python3-installer
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel

Requires:       python3
Requires:       python3-evdev
Requires:       python3-rich
Requires:       python3-yaml

%description
Handheld Daemon is a project that aims to provide utilities for managing handheld devices. With features ranging from TDP controls, to controller remappings, and gamescope session management. This will be done through a plugin system and an HTTP(/d-bus?) daemon, which will expose the settings of the plugins in a UI agnostic way.

%prep
%autosetup -n %{name}-%{version}

%build
%{python3} -m build --wheel --no-isolation

%install
%{python3} -m installer --destdir="%{buildroot}" dist/*.whl
mkdir -p %{buildroot}%{_udevrulesdir}
install -m644 usr/lib/udev/rules.d/83-%{name}.rules %{buildroot}%{_udevrulesdir}/83-%{name}.rules
mkdir -p %{buildroot}%{_unitdir}
install -m644 usr/lib/systemd/system/%{name}@.service %{buildroot}%{_unitdir}/%{name}@.service

%files
%doc readme.md
%license LICENSE
%{_bindir}/%{name}*
%{python3_sitelib}/%{name}*
%{_udevrulesdir}/83-%{name}.rules
%{_unitdir}/%{name}@.service
