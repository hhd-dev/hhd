Name:           hhd-git
Version:        {{{ git_dir_version }}}
Release:        2%{?dist}
Summary:        Handheld Daemon, a tool for configuring handheld devices.

License:        LGPL-2.1-or-later
URL:            https://github.com/hhd-dev/hhd
VCS:            {{{ git_dir_vcs }}}
Source:        	{{{ git_dir_pack }}}

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
{{{ git_dir_setup_macro }}}

%build
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
# %{_datarootdir}/dbus-1/system.d/hhd-net.hadess.PowerProfiles.conf