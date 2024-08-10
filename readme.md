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
It features a fully functional controller emulator that exposes gyro,
paddles, LEDs and QAM across Steam, RPCS3, Dolphin and others.
In addition, it features TDP controls all Ryzen devices and bespoke manufacturer
controls for the Legion Go and ROG Ally.
It brings all supported devices up to parity with Steam Deck.
Read [supported devices](#supported-devices) to see if your device is supported.

Handheld Daemon exposes configuration through an API, with a gamemode overlay
(double press/hold Side Menu), Decky plugin ([hhd-decky](https://github.com/hhd-dev/hhd-decky)),
web app ([hhd.dev](https://hhd.dev)) and desktop app
([hhd-ui](https://github.com/hhd-dev/hhd-ui)).

*Current Features*:
- DualSense and Dualsense Edge emulation
  - All buttons supported
  - Rumble feedback
  - Touchpad support (Steam Input as well)
  - LED remapping
- Xbox Elite emulation
  - No weird glyphs
  - Back button support
- Extra buttons as:
  - Steam Keyboard + Overlay Shortcuts
  - Left/Right Touchpad clicks in Dualsense mode (supported by Steam + Dualsense Games)
- Complete SDL UInput Emulation (currently disabled, see https://github.com/libsdl-org/SDL/issues/9688 )
  - Joycon (Left, Right, Pair), Switch Pro, Dualsense (Edge), Xbox One, Xbox Series X, Xbox 360
  - Gyro + Paddles for all SDL apps 
- Virtual Touchpad Emulation
  - Fixes left and right clicks within gamemode when using the device touchpad.
- Power Button plugin for Big Picture/Steam Deck Mode
  - Short press makes Steam backup saves and wink before suspend.
  - Long press opens Steam power menu.
- TDP Controls ([adjustor](https://github.com/hhd-dev/adjustor))
  - For ROG Ally and Legion Go: 
    - TDP, Fan Curves, Charge Limiting the Asus and Lenovo way
    - Asus: Kernel Driver
    - Lenovo: `acpi_call` while the kernel driver is being developed
  - For Other Devices without firmware TDP controls:
    - `acpi_call` + AMD's official manufacturer TDP ACPI bindings
    - Ayaneo, Ayn, GPD, OneXPlayer
- Configuration:
  - Fully Featured Gamemode (Gamescope) Overlay
  - Desktop App
  - Web app
  - Config files
- Built-in updater.

## Showcase
![Overlay](./docs/overlay.gif)

## <a name="devices"></a>Supported Devices
The following devices have been verified to work correctly, with TDP, QAM, 
Paddles/extra buttons, RGB remapping, Touchpad, and Gyro support.
The gyro axis might be incorrect for some of those devices, and can be easily
fixed in the configuration menu by following [these steps](#axis).
If you do take the time, please open an issue with the correct mapping so it
is added to your device.

- Legion Go
- Asus ROG
  - Ally
  - Ally X
- GPD Win (Both 2023/2024)
  - Win 4 (No LEDs)
  - Win Mini
  - Win Max 2
- MSI
  - Claw A1M (only front buttons)
- Ayaneo
  - Air Standard/Plus/Pro
  - 1S/1S Limited
  - 2/2S 
  - GEEK, GEEK 1S 
  - NEXT Lite/Pro/Advance
  - SLIDE
  - 2021 Standard/Pro/Pro Retro Power
  - NEO 2021/Founder
- Ayn
  - Loki Zero/Max
- AOKZOE (No LEDs)
  - A1 Normal/Pro
- Onexplayer (No LEDs)
  - Mini Pro
  - F1, F1 EVA-01
  - Mini A07
  - 2 APR23, 2 PRO APR23, 2 PRO APR23 EVA-01
- Ambernic
  - Win600 (no keyboard button yet)

In addition, Handheld Daemon will attempt to work on Ayaneo, Ayn, Onexplayer, and 
GPD Win devices that have not been verified to work 
(controller emulation will be off on first start).
If everything works and you fix the gyro axis for your device, open an issue
so that your device can be added to the supported list.
The touchpad will not work for devices not on the supported list.
Help is needed for OneXPlayer/AOKZOE LED Support.

## Installation Instructions
For Arch and Fedora see [here](#os-install).
For others, you can use the following script to install a local version of
Handheld Daemon that updates independently of the system.
```bash
curl -L https://github.com/hhd-dev/hhd/raw/master/install.sh | bash
```

This script does not automatically install system dependencies.
A partial list for Ubuntu/Debian can be found [here](#debian).
Then see [here](./kernel.md) for a partial list of kernel 
patches. This includes `acpi_call` for TDP on devices other than the Ally.

As Handheld Daemon matures, this list will continue to grow, so consider
a gaming distro such as Bazzite for your gaming needs.

### Uninstall
We are sorry to see you go, use the following to uninstall:
```bash
curl -L https://github.com/hhd-dev/hhd/raw/master/uninstall.sh | bash
```

### Using an older version
If you find any issues with the latest version of Handheld Daemon
you can use any version by specifying it with the command below.
```bash
sudo systemctl stop hhd_local@$(whoami)
~/.local/share/hhd/venv/bin/pip install hhd==2.6.0
sudo systemctl start hhd_local@$(whoami)
```

### <a name="issues"></a>After Install Instructions
#### Extra steps for ROG Ally
You can hold the ROG Crate button to switch to the ROG Ally's Mouse mode to turn
the right stick into a mouse.

Combinations with the ROG, Armory Crate buttons is not supported in the Ally,
you can swap them with start/select for this functionality.

#### Extra steps GPD Win Devices
In order for the back buttons in GPD Win Devices to work, you need to map the
back buttons to Left: PrintScreen, Right: Pausc using Windows (onscreen keyboard?).
This is the default mapping, so if you never remapped them using Windows you
will not have to.
Handheld Daemon automatically handles the interval to enable being able to hold
the buttons.

Here is how the button settings should look:
```
Left-key: PrtSc + 0ms + NC + 0ms + NC + 0ms + NC
Right-key: Pausc + 0ms + NC + 0ms + NC + 0ms + NC
```

Unfortunately, it is not possible to rapid double tap the buttons due to their
implementation.
The R4 button is mapped to Side Menu (QAM) by default.

#### Extra steps for Ayaneo/Ayn/Onexplayer
You might experience a tiny amount of lag with the Ayaneo LEDs.
The paddles of the Ayn Loki Max are not remappable as far as we know.

#### Extra steps for Legion Go
If you have set any mappings on Legion Space, they will interfere with Handheld
Daemon.
You can factory reset the Controllers from the Handheld Daemon settings.

The controller gyros of the Legion Go tend to drift and have noise.
However, they are excellent after calibration.
Calibrate them using steam calibration and be patient, as they will fail a lot.
Depending on their state in rare cases they might not be possible to calibrate.

If you are using a kernel older than 6.8, and you are not on a gaming distro
(Nobara, Bazzite), you need the following rule for the controllers
to be recognized.
```bash
# Enable xpad for the Legion Go controllers
ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6182", RUN+="/sbin/modprobe xpad" RUN+="/bin/sh -c 'echo 17ef 6182 > /sys/bus/usb/drivers/xpad/new_id'"
```

#### High Touchpad Sensitivity in Steam Input
By default, the Dualsense kernel driver exposes the Dualsense trackpad as a normal
trackpad.
This means that if you go to use it as steam input, you still get the normal
trackpad input.
This leads to double input.
You should use the package `ds-inhibit` to fix that, which detects steam and mutes
the trackpad while Steam is running.
The package `ds-inhibit` is available in AUR, packaged for Nobara, and enabled
by default in Bazzite.

#### Playstation Glyphs and Controller Image
New steam versions allow for universal glyphs that are controller agnostic,
for when using the Dualsense output option.
In addition, the new default Xbox option has the familiar Xbox layout.
If you are willing to install Decky, which has certain stability issues
as steam updates, Bazzite vendors a controller css theme 
for Decky that changes playstation glyphs.

## <a name="configuration"></a>Configuration
Open the overlay (double press side button), or open the desktop app (`Handheld Daemon`/`$ hhd-ui`),
or go to [hhd.dev](https://hhd.dev) and enter your device token (`~/.config/hhd/token`).
Then just start configuring!

While deprecated, the Decky plugin is still available:
```
curl -L https://github.com/hhd-dev/hhd-decky/raw/main/install.sh | sh
```

The configuration files are stored under `~/.config/hhd` with the main one being
`state.yml`, which can be edited and will hot reload.

## <a name="os-install"></a> Distribution Install
You can install Handheld Daemon from [AUR](https://aur.archlinux.org/packages/hhd) 
(Arch) or [COPR](https://copr.fedorainfracloud.org/coprs/hhd-dev/hhd/) (Fedora).
Both update automatically every time there is a new release.
For Debian/Ubuntu see below.

```bash
# Arch
yay -S hhd adjustor hhd-ui

# Fedora
sudo dnf copr enable hhd-dev/hhd
sudo dnf install hhd adjustor hhd-ui

sudo systemctl enable hhd@$(whoami)
```

### <a name="debian"></a> Debian/Ubuntu
The following packages are required for local install to work on Ubuntu/Debian.
Handheld daemon is not packaged for apt yet.
```bash
sudo apt install \
    libgirepository1.0-dev \
    libcairo2-dev \
    libpython3-dev \
    python3-venv \
    libhidapi-hidraw0
```

### ❄️ NixOS
Handheld Daemon (core; no overlay, TDP) is on `nixpkgs` in the `unstable` channel.

Add the following to your `configuration.nix` to enable:
```nix
  services.handheld-daemon.enable = true;
  services.handheld-daemon.user = "<your-user>";
```

### <a name="bazzite"></a><a name="after-install"></a>Bazzite
Handheld Daemon comes pre-installed on [Bazzite](https://bazzite.gg) and 
updates along-side the system.
Most users of Handheld Daemon are on Bazzite and Bazzite releases
often happen for Handheld Daemon to update.
Bazzite contains all kernel patches and quirks required for all supported handhelds
to work (to the extent they can; certain Ayaneo devices have issues).

If you want to test the development Handheld Daemon version you
can use `ujust _hhd-dev` and give feedback.
It will only last until you reboot and leave no changes to your system.
After changes are deemed stable, they usually are incorporated to Bazzite
after a few days.

See [supported devices](#supported-devices) to check the status of your device and 
[after install](#issues) for specific device quirks.

## Contributing
### <a name="axis"></a> Finding the correct axis for your device
To figure the correct axis from your device, go to steam calibration settings.
Then, in the overlay (double press/hold side button) switch `Motion Axis` to 
`Override` and tweak only the axis (without invert) of your device until they 
match the glyphs in steam.

Then, jump in a first person game and turn on `Gyro to Mouse` or `Camera`.
By default (`Yaw`), rotating your device like a steering wheel should turn left 
to right,
and rotating it to face down or up should look up or down.
Fix the invert settings of the axis so that it is intuitive.
Finally, switch the setting `Gyro Turning Axis` from `Yaw` (rotate like a steering
wheel) to `Roll` (turn left to right), and fix the remaining axis inversion.

You can now either take a picture of your screen or translate the settings into
text (e.g., x is k, y is l inverted, z is j) and open an issue.
The override setting also displays the make and model of your device, which
are required to add the mappings to Handheld Daemon.

### Localizing Handheld Daemon
Handheld Daemon fully supports localization through standard `PO`, `POT` files.
Contribution instructions in progress!!!

#### For maintainers
You can find `pot` and `po` files for Handheld Daemon under the `i18n` directory.
You can clone/download this repository and open the `./i18n` directory.
Then, just copy the `*.pot` files into `<your_locale>/LC_MESSAGES/*.po`
and begin translating with your favorite text editor, or by using
tool such as [Lokalize](https://apps.kde.org/lokalize/).

As far as your locale goes, unless you have a good reason to, skip the territory
code (e.g., `el` instead of `el_GR`).

The files can be updated for a new version with the following commands:
```bash
# Prepare dev environment
git clone https://github.com/hhd-dev/hhd
cd hhd
python -m venv venv
pip install babel
pip install -e .

# Regenerate POT files
pybabel extract --no-location -F i18n/babel.cfg -o i18n/hhd.pot src/hhd
# Assuming adjustor is in an adjacent directory
pybabel extract --no-location -F i18n/babel.cfg -o i18n/adjustor.pot ../adjustor/src/adjustor

# Generate PO files for your language if they do not exist
pybabel init -i i18n/hhd.pot -d i18n -D hhd -l YOUR_LANG
pybabel init -i i18n/adjustor.pot -d i18n -D adjustor -l YOUR_LANG

# Update current PO files for your language
pybabel update -i i18n/hhd.pot -d i18n -D hhd -l YOUR_LANG
pybabel update -i i18n/adjustor.pot -d i18n -D adjustor -l YOUR_LANG
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

# License
Handheld Daemon is licensed under THE GNU GPLv3+. See LICENSE for details.
A small number of files are dual licensed with MIT, and contain
SPDX headers denoting so. 
Versions prior to and excluding 2.0.0 are licensed using MIT.
