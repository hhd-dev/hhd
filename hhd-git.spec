# This spec is evaluated from a Git checkout. Build it from the repository root:
#   rpmbuild -ba hhd-git.spec
%global commit %(git rev-parse --verify HEAD)
%global shortcommit %(git rev-parse --short=12 %{commit})
%global gitversion %(tag=$(git describe --tags --abbrev=0 --match 'v[0-9]*' %{commit} 2>/dev/null || :); if test -n "$tag"; then version=${tag#v}; commits=$(git rev-list --count "$tag..%{commit}"); if test "$commits" -eq 0; then printf '%%s' "$version"; else printf '%%s+git.%%s.g%%s' "$version" "$commits" "%{shortcommit}"; fi; else commits=$(git rev-list --count %{commit}); printf '0.0.0+git.%%s.g%%s' "$commits" "%{shortcommit}"; fi)

Name:           hhd
Version:        %{gitversion}
Release:        1%{?dist}
Summary:        Handheld Daemon, a tool for configuring handheld devices.

License:        LGPL-2.1-or-later
URL:            https://github.com/hhd-dev/hhd
VCS:            git+%{URL}.git#%{commit}
Source0:        %{URL}/archive/%{commit}/%{name}-%{commit}.tar.gz

BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
BuildRequires:  python3-devel
BuildRequires:  python3-build
BuildRequires:  python3-installer
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  python3-babel

Requires:       python3
Requires:       python3-evdev
Requires:       python3-rich
Requires:       python3-yaml
Requires:       python3-setuptools
Requires:       python3-xlib
Requires:       python3-pyserial
Requires:       python3-pyroute2
Requires:       python3-gobject
Requires:       libusb1
Requires:       hidapi

Provides:       hhd

%description
Handheld Daemon is a project that aims to provide utilities for managing handheld devices. With features ranging from TDP controls, to controller remappings, and gamescope session management. This will be done through a plugin system and an HTTP(/d-bus?) daemon, which will expose the settings of the plugins in a UI agnostic way.

%prep
%autosetup -n %{name}-%{commit}

%build
sed -i -E 's/^version = ".*"/version = "%{version}"/' pyproject.toml
%{python3} -m babel.messages.frontend compile -D hhd -d ./i18n
%{python3} -m babel.messages.frontend compile -D adjustor -d ./i18n || true
cp -rf ./i18n/* ./src/hhd/i18n
%{python3} -m build --wheel --no-isolation

%install
%{python3} -m installer --destdir="%{buildroot}" dist/*.whl
mkdir -p %{buildroot}%{_udevrulesdir}
install -m644 usr/lib/udev/rules.d/83-hhd.rules %{buildroot}%{_udevrulesdir}/83-hhd.rules
mkdir -p %{buildroot}%{_sysconfdir}/udev/hwdb.d
install -m644 usr/lib/udev/hwdb.d/83-hhd.hwdb %{buildroot}%{_sysconfdir}/udev/hwdb.d/83-hhd.hwdb
mkdir -p %{buildroot}%{_unitdir}
install -m644 usr/lib/systemd/system/hhd@.service %{buildroot}%{_unitdir}/hhd@.service
install -m644 usr/lib/systemd/system/hhd.service %{buildroot}%{_unitdir}/hhd.service

%files
%doc readme.md
%license LICENSE
%{_bindir}/hhd*
%{python3_sitelib}/hhd*
%{_udevrulesdir}/83-hhd.rules
%{_sysconfdir}/udev/hwdb.d/83-hhd.hwdb
%{_unitdir}/hhd@.service
%{_unitdir}/hhd.service

%{python3_sitelib}/adjustor*
# %%{_datarootdir}/dbus-1/system.d/hhd-net.hadess.PowerProfiles.conf
