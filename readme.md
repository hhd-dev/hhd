<h1 align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_dark.svg" width="50%">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_light.svg" width="50%">
        <img alt="Handheld Daemon Logo." src="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_light.svg" width="50%">
    </picture>
</h1>

[![PyPI package version](https://badge.fury.io/py/hhd.svg)](https://pypi.org/project/hhd/)
[![Python version 3.10+](https://img.shields.io/badge/python-3.10%2B-informational.svg)](https://pypi.org/project/pasteur/)
[![Code style is Black](https://img.shields.io/badge/code%20style-black-black.svg)](https://github.com/psf/black)
<!-- [![]()]() -->

# Handheld Daemon
Handheld Daemon is a project that aims to provide utilities for managing handheld
devices.
Right now, it features a fully functional controller emulator that exposes gyro,
paddles, LEDs and QAM across Steam, Yuzu, Dolphin and others.
It brings all supported devices up to parity with Steam Deck.
Read [supported devices](#supported-devices) to see if your device is supported.

Handheld Daemon exposes configuration through an API, and there is already a Decky
plugin for it ([hhd-decky](https://github.com/hhd-dev/hhd-decky)) and a web
app for it ([hhd.dev](https://hhd.dev)) that also works locally with Electron
([hhd-ui](https://github.com/hhd-dev/hhd-ui)).

In addition, a new TDP plugin (currently non-functional) is in the works, that
will allow both vendor specific and vendor independent TDP controls.
Check out [adjustor](https://github.com/hhd-dev/adjustor)!.

*Current Features*:
- Fully functional DualSense and Dualsense Edge emulation
    - All buttons supported
    - Rumble feedback
    - Touchpad support (Steam Input as well)
    - LED remapping
- Xbox 360 Style device emulation
  - No weird glyphs
  - Gyro and back button support (outside Steam)
- Virtual Touchpad Emulation
  - Fixes left and right clicks within gamescope when using the device touchpad.
- Power Button plugin for Big Picture/Steam Deck Mode
    - Short press makes Steam backup saves and wink before suspend.
    - Long press opens Steam power menu.
- Hides the original Xbox controller
- UI based Configuration
  - Generic API that can be used from bash scripts (through `curl`)
  - Decky Plugin
  - Webapp on https://hhd.dev and through Electron.
- Built-in updater.

## <a name="devices"></a>Supported Devices
The following devices have been verified to work correctly, with QAM, 
Paddles/extra buttons, RGB remapping, Touchpad, and Gyro support.
The gyro axis might be incorrect for some of those devices, and can be easily
fixed in the configuration menu by following [these steps](#axis).
If you do take the time, please open an issue with the correct mapping so it
is added to your device.

- Legion Go
- ROG Ally
- GPD Win 
  - Win 4
  - Win Mini
  - Win Max 2 2023
- Ayaneo
  - Air Standard/Plus/Pro
  - 1S/1S Limited
  - 2/2S 
  - GEEK, GEEK 1S 
  - NEXT Lite/Pro/Advance
  - SLIDE
- Ayn
  - Loki Max
- AOKZOE
  - A1
  - A1 Pro 
- Onexplayer
  - Mini Pro

In addition, Handheld Daemon will attempt to work on Ayaneo, Ayn, Onexplayer, and 
GPD Win devices that have not been verified to work 
(controller emulation will be off on first start).
If everything works and you fix the gyro axis for your device, open an issue
so that your device can be added to the supported list.
The touchpad will not work for devices not on the supported list.

RGB support is not yet available for GPD Win 4, it is currently being investigated.
In addition, GPD Win 4's touch point acts like a mouse, so it unfortunately can not
be used for steam input.
Some devices do not support holding the power button to open steam settings on
the current version, this will be fixed in a future release.

## Installation Instructions
You can install the latest stable version of `hhd` from PyPi (recommended), AUR,
or COPR.
The easiest way to use Handheld Daemon is to install Bazzite which
comes pre-installed with the latest version and all required kernel
fixes for supported devices, see [here](#bazzite).
Nobara also packages hhd and it will become the default for supported devices soon.
However, it only packages fixes for the Ally and Legion Go at the time of this
writing.

> [!IMPORTANT]
> To ensure the gyro of the Legion Go with AMD SFH runs smoothly, 
> a udev rule is included that disables the use of the accelerometer by the 
> system (e.g., iio-sensor-proxy).
> If you want display auto rotation to work, see manual local steps.

### Automatic Local Install
You can use the following bash scripts to install and uninstall Handheld Daemon.
Then, update from Decky or the UI.
These steps do not work on Bazzite, see [here](#bazzite).

> If your distro uses HandyGCCS/Handycon to fix certain key bindings by default
> you need to uninstall it. Disabling it is not enough, since it is autostarted
> by certain sessions (such as `gamescope-session-plus`). 
> This includes both ChimeraOS and Nobara (see [Common Issues after Install](#issues)).

```bash
# Install
curl -L https://github.com/hhd-dev/hhd/raw/master/install.sh | sh

# Uninstall
curl -L https://github.com/hhd-dev/hhd/raw/master/uninstall.sh | sh
```

You can also install the Decky plugin.
Having Decky installed is a prerequisite ([instructions](https://github.com/SteamDeckHomebrew/decky-loader#-installation)).
```bash
curl -L https://github.com/hhd-dev/hhd-decky/raw/main/install.sh | sh
```

Then, reboot and go to [hhd.dev](https://hhd.dev) to configure or read more in
the [configuration section](#configuration).

> Before creating an issue, make sure you are using the latest Handheld Daemon 
> version and that you read the extra information for each setting in 
> either [hhd.dev](https://hhd.dev) or the `state.yml` file.
> 
> The context is required to understand what each setting does and is 
> not included in the current version of the Decky Plugin 
> due to UI limitations.

#### Using an older version
If you find any issues with the latest version of Handheld Daemon
you can use any version by specifying it with the command below.
```bash
sudo systemctl stop hhd_local@$(whoami)
~/.local/share/hhd/venv/bin/pip install hhd==1.0.6
sudo systemctl start hhd_local@$(whoami)
```

### Manual Local Installation
You can also install Handheld Daemon using a local package, which enables auto-updating.
These are the same steps as done in the Automatic Install (also see 
[Common Issues after Install](#issues)).
These steps do not work on Bazzite, see [here](#bazzite).

```bash
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# !!!! Uninstall HandyGCCS to avoid issues if you have it. !!!!
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# Install Handheld Daemon to ~/.local/share/hhd
mkdir -p ~/.local/share/hhd && cd ~/.local/share/hhd

python -m venv --system-site-packages venv
source venv/bin/activate
pip install --upgrade hhd
# Substitute with the following to pull from github (may not always work)
# pip install git+https://github.com/hhd-dev/hhd

# Install udev rules and create a service file
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/udev/rules.d/83-hhd.rules -o /etc/udev/rules.d/83-hhd.rules

# Change rules to re-enable display autorotation if you do not want gyro support.
# sudo nano /etc/udev/rules.d/83-hhd.rules

sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/systemd/system/hhd_local%40.service -o /etc/systemd/system/hhd_local@.service

# Start service and reboot
sudo systemctl enable hhd_local@$(whoami)
sudo reboot
```

#### Using an older version
If you find any issues with the latest version of Handheld Daemon
you can use any version by specifying it with the command below.
```bash
sudo systemctl stop hhd_local@$(whoami)
~/.local/share/hhd/venv/bin/pip install hhd==1.0.6
sudo systemctl start hhd_local@$(whoami)
```

#### Update Instructions
Of course, you will want to update Handheld Daemon to catch up to latest features.
You can either use the commands below or press `Update (Stable)` in one of the UIs
(which runs these commands).
```bash
sudo systemctl stop hhd_local@$(whoami)
~/.local/share/hhd/venv/bin/pip install --upgrade hhd
sudo systemctl start hhd_local@$(whoami)
```

#### Uninstall instructions
To uninstall, simply stop the service and remove the added files.
```bash
sudo systemctl disable hhd_local@$(whoami)
sudo systemctl stop hhd_local@$(whoami)
rm -rf ~/.local/share/hhd
sudo rm /etc/udev/rules.d/83-hhd.rules
sudo rm /etc/systemd/system/hhd_local@.service
# Delete your configuration
rm -r ~/.config/hhd
```

### <a name="issues"></a>After Install Instructions
#### Extra steps for ROG Ally
Without an up-to-date `asus-wmi` kernel driver the usb device of the controller
does not wake up after sleep so Handheld Daemon stops working.
This patch is included with Linux kernel 6.7.

See [here](#gyro) for the required kernel patches.
Without the patch series for the IMU (where patches 0001, and 0002 are included
in kernel 6.8), the gyro will not work.

You can hold the ROG Crate button to switch to the ROG Ally's Mouse mode to turn
the right stick into a mouse.

#### Extra steps GPD Win Devices
In order for the back buttons in GPD Win Devices to work, you need to map the
back buttons to Left: Printscreen, Right: Pause using Windows.
This is the default mapping, so if you never remapped them using Windows you
will not have to.
Handheld Daemon automatically handles the interval to enable being able to hold
the button.

Here is how the button settings should look:
```
Left-key: PrtSc + 0ms + NC + 0ms + NC + 0ms + NC
Right-key: Pausc + 0ms + NC + 0ms + NC + 0ms + NC
```

#### Extra steps for Ayaneo/Ayn/Onexplayer
See [here](#gyro) for the required kernel patches.
For led support in Ayaneo, you will need the 
[ayaneo-platform](https://github.com/ShadowBlip/ayaneo-platform)
driver, and for Ayn, the [ayn-platform](https://github.com/ShadowBlip/ayn-platform).
Provided these drivers are installed and are supported by your device,
LED support will be enabled by default.

The paddles of the Ayn Loki Max are not remappable as far as we know.

#### Extra steps for Legion Go
If you are using a kernel older than 6.8 and you are not on a gaming distro
(ChimeraOS, Nobara, Bazzite), you need the following rule for the controllers
to be recognized.
```bash
# Enable xpad for the Legion Go controllers
ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6182", RUN+="/sbin/modprobe xpad" RUN+="/bin/sh -c 'echo 17ef 6182 > /sys/bus/usb/drivers/xpad/new_id'"
```

If you have set any mappings on Legion Space, they will interfere with Handheld
Daemon.
In this case, you may reset your controllers by holding Legion R + RT + RB, 
and then Legion L + LT + LB or booting into windows.

#### <a name="gyro"></a>Gyro Kernel Drivers
Which kernel patch is required will depend on your device's bosch module.
For the Bosch 260 IMU, you will need the 
[bmi260-dkms](https://github.com/hhd-dev/bmi260) driver.
For the Bosch 160 IMU and certain devices, you will need the following bmi160
[kernel patch](https://github.com/pastaq/bmi160-aya-neo/blob/main/bmi160_ayaneo.patch).
Ayaneo Air Plus and Ally use the Bosch 323 and need the patch series from
this repository: [Ally Nobara Fixes](https://github.com/jlobue10/ALLY_Nobara_fixes). 
The Legion Go does not need kernel patches.

In addition, for most devices, your kernel config should also 
enable the modules `SYSFS trigger` with `CONFIG_IIO_SYSFS_TRIGGER` and
`High resolution timer trigger` with `CONFIG_IIO_HRTIMER_TRIGGER`.
Both are under `Linux Kernel Configuration ─> Device Drivers ─> Industrial I/O support ─> Triggers - standalone`.

#### Broken Steam Gyro Calibration
Steam gyro calibration does not corrently work due to an issue with the accelerometer
scale (bottom bar).
Since the accelerometer is not currently used for anything this is not a high
priority fix.
The gyro will work fine in games.

If you get drift, you can turn on `Auto-Calibrate Gyro Drift when Stationary` and
then move the top bar (gyro) right until it covers the noise.

#### High Touchpad Sensitivity in Steam Input
By default, the Dualsense kernel driver exposes the Dualsense trackpad as a normal
trackpad.
This means that if you go to use it as steam input, you still get the normal
trackpad input.
This leads to double input.

You can either disable it with the package `ds-inhibit` which detects if steam
is running and mutes it (still works in desktop) or with the following udev rule 
(does not work in desktop).
Place it under `/etc/udev/rules.d/99-hhd-playstation-touchpad.rules`
```bash
# Disables all playstation touchpads from use as touchpads.
ACTION=="add|change", KERNEL=="event[0-9]*", ATTRS{name}=="*Wireless Controller Touchpad", ENV{LIBINPUT_IGNORE_DEVICE}="1"
```

The package `ds-inhibit` is available in AUR, packaged for Nobara, and enabled
by default in Bazzite.

#### Playstation Glyphs and Controller Image
If you do not want playstation glyphs in Steam, you can use https://github.com/frazse/PS5-to-Xbox-glyphs
as a CSS Loader plugin to switch them to Xbox.
Then, there are CSS plugins for the Legion Go and Ally controller images in
https://github.com/frazse/SBP-Legion-Go-Theme and 
https://github.com/semakusut/SBP-ROG-Ally respectively.
If you are using Bazzite, you can also find a `ujust` version of the commands in 
the Bazzite readme.

#### Missing Python Evdev
In case you have installation issues, you might be missing the package `python-evdev`.
You can either install it as part of your distribution (included by Nobara
and ChimeraOS) or automatically through `pip` with the commands above.
However, installing this package through `pip` requires `base-devel` on Arch and
`python-devel` on Nobara.
```bash
# Nobara/Fedora
sudo dnf install python-evdev
# Arch based distros (included by ChimeraOs)
sudo pacman -S python-evdev

# OR

# (nobara) Install Python Headers since evdev has no wheels
# and nobara does not ship them (but arch does)
sudo dnf install python-devel
# (Chimera, Arch) In case you dont have gcc.
sudo pacman -S base-devel
```

#### Having HandyGCCS Installed
If your distro ships with HandyGCCS Handheld Daemon will not work, you have to uninstall it.
```bash
# ChimeraOS
sudo frzr-unlock
sudo systemctl disable --now handycon.service
sudo pacman -R handygccs-git

# Nobara
sudo systemctl disable --now handycon.service
sudo dnf remove handygccs-git # (verify ?)
```

### <a name="bazzite"></a><a name="after-install"></a>Bazzite
Handheld Daemon comes pre-installed on Bazzite and updates along-side the system.
The latest version of Handheld Daemon becomes available at the latest the next
day after release, and can be managed through the Bazzite updater.
In addition, Bazzite contains all the required kernel patches for the Handheld Daemon
supported devices, so it is the recommended distro to use Handheld Daemon with.

After install, you can use `ujust` to install Decky and the Handheld Daemon Decky
plugin with the commands `ujust get-decky`, `ujust get-hhd-decky`.

If you need to use a different Handheld Daemon version or a custom one, the 
install steps do not currently work for Bazzite, but this will be fixed in the future.
Essentially, a new service file needs to be written for Bazzite that contains the
correct home path (`/var/home`) and then you can disable the built-in version
service and use the new one instead.

See [supported devices](#supported-devices) to check the status of your device and 
[after install](#issues) for specific device quirks.

### ❄️ NixOS
Ensure your `nixpkgs` is on the `unstable` channel (as of Feb 2024):

```nix
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
```

and add this line to your `configuration.nix`:
```nix
  services.handheld-daemon.enable = true;
```

### Distribution Installation (not recommended)
You can install Handheld Daemon from [AUR](https://aur.archlinux.org/packages/hhd) 
(Arch) or [COPR](https://copr.fedorainfracloud.org/coprs/hhd-dev/hhd/) (Fedora).
Both update automatically every time there is a new release.

But, the auto-updater will not work, which is an important feature with devices
without a keyboard.
```bash
# Arch
yay -S hhd

# Fedora
sudo dnf copr enable hhd-dev/hhd
sudo dnf install hhd

# Enable and reboot
sudo systemctl enable hhd@$(whoami)
sudo reboot
```

In case you do not want to reboot.
```bash
# Reload Handheld Daemon's udev rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# Restart iio-proxy-service to stop it
# from polling the accelerometer
sudo systemctl restart iio-sensor-proxy
# Start the service for your user
sudo systemctl start hhd@$(whoami)
```

## <a name="configuration"></a>Configuration
### UI Based
Go to [hhd.dev](https://hhd.dev) and enter your device token 
(`~/.config/hhd/token`).
That is it!
You can also install the Electron version ([hhd-ui](https://github.com/hhd-dev/hhd-ui)) 
to use completely offline or as an app (updating it has to be done manually for now).

### Using Decky
If you have decky installed, you can use the following command to
install the Handheld Daemon decky plugin (visit 
[hhd-decky](https://github.com/hhd-dev/hhd-decky) for details).
```
curl -L https://github.com/hhd-dev/hhd-decky/raw/main/install.sh | sh
```
Then, just open up steam.

### File based
The reason you added your username to the `hhd` service was to bind the `hhd`
daemon to your user.

This allows Handheld Daemon to add configuration files with appropriate
permissions to your user, in the following directory:
```bash
~/.config/hhd
```

The global configuration for HHD is found in:
```bash
~/.config/hhd/state.yml
```

You can modify it and it will hot-reload upon saving.

## Contributing
### <a name="axis"></a> Finding the correct axis for your device
To figure the correct axis from your device, go to desktop and open the steam
calibration settings.
Then, go to https://hhd.dev , switch `Motion Axis` to `Override` and tweak only
the axis (without invert) of your device until they match the glyphs in steam.

> [!WARNING]  
> Do not try to interpret what each axis means. You will get a headache. 
> Just change them randomly until
> the glyphs line up with how you move your controller.
> If you set multiple axis to a single one (e.g., X to Y, and Y to Y),
> the first option (e.g., X to Y) option will be ignored.

Then, jump in a first person game and turn on `Gyro to Mouse` or `Camera`.
For `Gyro to Mouse`, use `Gyro to Mouse fix` if you get issues with the camera
jumping around.
By default, rotating your device like a steering wheel should turn left to right,
and rotating it to face down or up should look up or down.
Fix the invert settings of the axis so that it is intuitive.
Finally, switch the setting `Gyro Turning Axis` from `Yaw` (rotate like a steering
wheel) to `Roll` (turn left to right), and fix the remaining axis inversion.

You can now either take a picture of your screen or translate the settings into
text (e.g., x is k, y is l inverted, z is j) and open an issue.
The override setting also displays the make and model of your device, which
are required to add the mappings to Handheld Daemon.

### Localizing Handheld Daemon
You can find `pot` and `po` files for Handheld Daemon under the  `i18n` directory.
You can clone/download this repository and open the `./i18n` directory.
Then, just copy the `template.pot` file into `<your_locale>/LC_MESSAGES/messages.po`
and begin translating with your favorite text editor, or by using
tool such as [Lokalize](https://apps.kde.org/lokalize/).

The files can be updated for a new version with the following commands:
```bash
# Prepare dev environment
git clone https://github.com/hhd-dev/hhd
cd hhd
python -m venv venv
pip install babel
pip install -e .

# Generate POT file
pybabel extract --no-location -F i18n/babel.cfg -o i18n/template.pot src/hhd
# Update current pot files
pybabel update -i i18n/template.pot -d i18n -D hhd
# Generate PO files for your language (essentially a copy with a header change)
pybabel init -i i18n/template.pot -l el_gr -d i18n -D hhd
```

### Creating a Local Repo version
Either follow `Automatic Install` or `Manual Local Install` to install the base rules.
Then, clone, optionally install the userspace rules, and run.
```bash
# Clone Handheld Daemon
git clone https://github.com/hhd-dev/hhd
cd hhd
python -m venv venv
source venv/bin/activate
pip install -e .

# Install udev rules to allow running without sudo (optional)
# but great for debugging (not all devices will run properly, the rules need to be expanded)
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/udev/rules.d/83-hhd-user.rules -o /etc/udev/rules.d/83-hhd-user.rules
# Modprobe uhid to avoid rw errors
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/modules-load.d/hhd-user.conf -o /etc/modules-load.d/hhd-user.conf
# You can now run hhd in userspace!
hhd

# Use the following to run with sudo
sudo hhd --user $(whoami)
```