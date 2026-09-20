<h1 align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_dark.svg" width="50%">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_light.svg" width="50%">
        <img alt="Handheld Daemon Logo." src="https://raw.githubusercontent.com/hhd-dev/hhd/master/art/logo_light.svg" width="50%">
    </picture>
</h1>

[![PyPI package version](https://badge.fury.io/py/hhd.svg)](https://pypi.org/project/hhd/)
[![Python version 3.12+](https://img.shields.io/badge/python-3.12%2B-informational.svg)](https://pypi.org/project/pasteur/)
[![Code style is Black](https://img.shields.io/badge/code%20style-black-black.svg)](https://github.com/psf/black)
[![Translations on Weblate](https://hosted.weblate.org/widget/hhd/hhd/svg-badge.svg)](https://hosted.weblate.org/engage/hhd/)
[![Discord for Support](https://img.shields.io/discord/1451243296688181342?logo=discord)](https://discord.com/invite/QSzseNYFMF)
<!-- [![]()]() -->

# Handheld Daemon
Handheld Daemon provides hardware enablement for Windows handhelds, so that they run correctly in Linux. It acts as a vendor interface replacement (e.g., Armoury Crate equivalent), with fan curves, TDP controls, controller emulation including gyro, back buttons, and SteamOS shortcuts, and RGB remapping. All of this is through a gamescope overlay, accessible through double tapping the side menu button of the device, and a desktop app.

## Showcase
![Overlay](./docs/overlay.gif)

## <a name="devices"></a>Supported Devices
Handheld Daemon features great support for Lenovo, Asus, GPD, OneXPlayer, and Ayn. It also features some support for Ayaneo devices, Anbernic, and MSI. We aim to support new models by these manufacturers as they release, so if you don't see your device below, chances are it will still work or just needs to have its config included.

- Lenovo Legion
  - Go
  - Go S
  - Go 2
- Asus ROG
  - Ally
  - Ally X
  - Xbox Ally
  - Xbox Ally X
  - Z13
- GPD Win (all model years)
  - Win 4
  - Win Mini (2025 model has no WinControls integration)
  - Win Max 2
  - Win Max 5
- OneXPlayer
  - G1 (AMD, Intel w/o TDP)
  - X1, X1Pro (AMD, Intel w/o TDP), X1z, X1Pro EVA-01, X1 Air (Intel-no TDP)
  - X1 Mini, X1 Mini Pro
  - X2Mini Pro
  - F1, F1 EVA-01, F1L, F1 OLED, F1 Pro
  - 2, 2 APR23, 2 PRO APR23, 2 PRO APR23 EVA-01
  - Mini A07
  - Mini Pro
  - ONE XPLAYER
- MSI
  - Claw 1st Gen (needs older bios-maybe not anymore, has wifi issues after sleep)
  - Claw 7/8 AI+ (no gyro)
  - Claw A8 (minor TDP issues, no gyro)
- Zotac
  - Zotac Gaming Zone (1st gen; only front buttons; be in gamepad mode before installing Linux)
- Ayn
  - Loki MiniPro/Zero/Max
- TECTOY
  - Zeenix Pro (rebranded Loki Max)
- Ayaneo
  - Ayaneo 3 (full support including magic modules) 
  - Air Standard/Plus/Pro
  - 1S/1S Limited
  - 2/2S
  - GEEK, GEEK 1S 
  - NEXT Lite/Pro/Advance
  - SLIDE
  - 2021 Standard/Pro/Pro Retro Power
  - NEO 2021/Founder
  - KUN (only front buttons, no RGB)
- AOKZOE
  - A1 Normal/Pro (No LEDs)
  - A2 Pro (No LEDs)
  - A1X
- Anbernic
  - Win600 (no keyboard button yet)
- TECNO
  - Pocket Go (all buttons except bottom switch and gyro; no RGB)
- Mystin Labs
  - SuiPlay 0x1

## <a name="installation"></a> Installation Instructions
If you want to access Handheld Daemon's expanded functionality, you should use the [Anatase](https://github.com/anatase-org/anatase) distribution. It carries the latest tested commit in its latest version (i.e., not on a github release). 

Unfortunately, as Handheld Daemon integrates closer with the kernel due to secure boot requirements and gamescope to provide features such as framegen, using a freefloating mainline kernel version will increasingly break devices. This is is compounded by highly complicated controller drivers that are introduced in the kernel using a Valve copyright and do not properly work.

For basic desktop use, you may use the following script to install a local version of Handheld Daemon that updates independently of the system.
```bash
curl -L https://github.com/hhd-dev/hhd/raw/master/install.sh | bash
```

This should work in Ubuntu, Arch, and Fedora. It will break when your system python updates to a new version, so you will need to run the install script again when that happens. This script does not automatically install system dependencies. You should fish what those are based on error messages and by inspecting close issues in this tracker.

Using COPR or AUR, even though the packages are available straight from this repository there, is not recommended. COPR is not because you're more likely to break your system by using it (just rerun the install script after updating Fedora versions), and AUR, because it is going through a hard time.

It is not recommended to run Handheld Daemon on nix. Lots of people have tried, but around 20% of its functionality silently breaks.

## Contributing
### <a name="axis"></a> Finding the correct axis for your device
To figure the correct axis from your device, go to steam calibration settings. Then, in the overlay (double press/hold side button) switch `Motion Axis` to  `Override` and tweak only the axis (without invert) of your device until they  match the glyphs in steam.

Then, jump in a first person game and turn on `Gyro to Mouse` or `Camera`. By default (`Yaw`), rotating your device like a steering wheel should turn left  to right, and rotating it to face down or up should look up or down. Fix the invert settings of the axis so that it is intuitive. Finally, switch the setting `Gyro Turning Axis` from `Yaw` (rotate like a steering wheel) to `Roll` (turn left to right), and fix the remaining axis inversion.

You can now either take a picture of your screen or translate the settings into text (e.g., x is k, y is l inverted, z is j) and open an issue. The override setting also displays the make and model of your device, which are required to add the mappings to Handheld Daemon.

### Localizing Handheld Daemon

#### On Weblate (Recommended)
[![Translations on Weblate](https://hosted.weblate.org/widget/hhd/hhd/svg-badge.svg)](https://hosted.weblate.org/engage/hhd/)

You can help translate Handheld Daemon on [Weblate](https://hosted.weblate.org/engage/hhd/).
It is a free service for open source projects, and it makes it easy to contribute
translations without having to deal with `git` or `po` files.
You can also use it to see the current translation status of Handheld Daemon.

#### For maintainers
Handheld Daemon fully supports localization through standard `PO`, `POT` files.

You can find `pot` and `po` files for Handheld Daemon under the `i18n` directory. You can clone/download this repository and open the `./i18n` directory. Then, just copy the `*.pot` files into `<your_locale>/LC_MESSAGES/*.po` and begin translating with your favorite text editor, or by using tool such as [Lokalize](https://apps.kde.org/lokalize/).

As far as your locale goes, unless you have a good reason to, skip the territory code (e.g., `el` instead of `el_GR`).

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

YOUR_LANG=el

# Generate PO files for your language if they do not exist
pybabel init -i i18n/hhd.pot -d i18n -D hhd -l $YOUR_LANG
pybabel init -i i18n/adjustor.pot -d i18n -D adjustor -l $YOUR_LANG

# Update current PO files for your language
pybabel update -i i18n/hhd.pot -d i18n -D hhd -l $YOUR_LANG
pybabel update -i i18n/adjustor.pot -d i18n -D adjustor -l $YOUR_LANG
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
Handheld Daemon is licensed under THE GNU LESSER GENERAL PUBLIC LICENSE v2.1 or later. See LICENSE for details. A small number of files are dual licensed with MIT, and contain SPDX headers denoting so.

# Credits
Much like a lot of open-source projects, Handheld Daemon is a community effort.It relies on the kernel drivers [oxp-sensors](https://github.com/torvalds/linux/blob/master/drivers/hwmon/oxp-sensors.c), [ayn-platform](https://github.com/ShadowBlip/ayn-platform), [ayaneo-platform](https://github.com/ShadowBlip/ayaneo-platform), [bmi260](https://github.com/hhd-dev/bmi260), [gpdfan](https://github.com/Cryolitia/gpd-fan-driver/),and [asus-wmi](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/asus-wmi.c).In addition, certain parts of Handheld Daemon reference the reverse engineeringefforts of [asus-linux](https://gitlab.com/asus-linux), the [Handheld Companion](https://github.com/Valkirie/HandheldCompanion) project,the [ValvePython](https://github.com/ValvePython) project, [pyWinControls](https://github.com/pelrun/pyWinControls), and the [HandyGCCS](https://github.com/ShadowBlip/HandyGCCS) project.Finally, its functionality is made possible thanks to thousands of hours of volunteer testing, who have provided feedback and helped shape the project.Some of those volunteers integrated support for their devices directly, especiallyin the case of Ayaneo, GPD, and for the initial support of OneXPlayer, and ROG Ally devices.
