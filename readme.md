# Handheld Daemon (HHD)
Handheld Daemon is a project that aims to provide utilities for managing handheld
devices.
With features ranging from TDP controls, to controller remappings, and gamescope 
session management.

This configuration is exposed through an API, and there is already a Decky
plugin for it ([hhd-decky](https://github.com/hhd-dev/hhd-decky)) and a web
app for it ([hhd.dev](https://hhd.dev)) that also works locally with Electron
([hhd-ui](https://github.com/hhd-dev/hhd-ui)).

It is the aim of this project to provide generic hid-based emulators for most
mainstream controllers (xbox Elite, DS4, PS5, Joycons), so that users of devices
can pick the best target for their device and its controls, which may change
depending on the game.

*Supported Devices*:
- Legion Go
- ROG Ally
- GPD Win 4, Win Mini, and Win Max 2 2023
- Ayaneo Air Plus

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

*Planned Features (in this order)*:
- Steam Deck controller emulation
  - No weird glyphs
- TDP Plugin
  - Will provide parity with Legion Space/Armory crate, hardware is already reverse 
    engineered for the Legion Go.
- High-end Over/Downclocking Utility for Ryzen processors
  - By hooking into the manufacturer ACPI API of the Ryzen platform,
    it will expose all TDP related parameters manufacturers have access to
    when spec'ing laptops.
  - No memory-relaxed requirement
  - Safe, as it is the method used by manufacturers (provided you stay within limits).

## Installation Instructions
You can install the latest stable version of `hhd` from PyPi (recommended), AUR,
or COPR.
The easiest way to use Handheld Daemon is to install Bazzite which
comes pre-installed with the latest version and all required kernel
fixes for supported devices, see [here](#bazzite).

> [!WARNING]  
> There is a bug that breaks how Dualsense controllers are parsed in Steam in various
> distros, which causes Gyro, LEDs, and paddles to not be detected in Steam, 
> and the Dualsense Edge mapping being very wrong.
> ChimeraOS 45, and certain versions of Nobara 38, and 39 also have this issue.
> It is being investigated.

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

### <a name="issues"></a> Common Issues with Install
#### Extra steps for ROG Ally
Using the gyroscope on the Ally requires a kernel that is patched to enable IMU
support.
See [Ally Nobara Fixes](https://github.com/jlobue10/ALLY_Nobara_fixes) for IMU the
patches themselves (IMU 0001-0005) and Fedora kernel binaries 
(install with `sudo rmp -i <img>.rpm`)
and [rog-ally-gaming/linux-chimeraos](https://github.com/rog-ally-gaming/linux-chimeraos)
for Arch distribution binaries (install with `sudo pacman -U <img>.tar.xz`; except 6.1 kernels).

If you compile your own kernel, your kernel config should also enable the
modules `SYSFS trigger` with `CONFIG_IIO_SYSFS_TRIGGER` and
`High resolution timer trigger` with `CONFIG_IIO_HRTIMER_TRIGGER`.
Both are under `Linux Kernel Configuration ─> Device Drivers ─> Industrial I/O support ─> Triggers - standalone`.

Without an up-to-date `asus-wmi` kernel driver the usb device of the controller
does not wake up after sleep so Handheld Daemon stops working.
This patch is included with Linux kernel 6.7.

Without the patch series for the IMU (where patches 0001, and 0002 are included
in kernel 6.8), the gyro will not work and if the `Motion` option is enabled,
LEDs will not work either, so that should be turned off.

You can hold the ROG Crate button to switch to the ROG Ally's Mouse mode to turn
the right stick into a mouse.

#### Extra steps GPD Win Devices
In order for the back buttons in GPD Win Devices to work, you need to map the
back buttons to Left: Pause, Right: Printscreen using Windows.
This is the default mapping, so if you never remapped them using Windows you
will not have to.
Handheld Daemon automatically handles the interval to enable being able to hold
the button.

Here is how the button settings should look:
```
Left-key: PrtSc + 0ms + NC + 0ms + NC + 0ms + NC
Right-key: Pausc + 0ms + NC + 0ms + NC + 0ms + NC
```

To use the gyro, you will need a [dkms package](github.com/hhd-dev/bmi260)
for the Bosch 260 IMU Driver.
Follow the instructions in that repository to install it.

In addition, for devices other than the Win Mini, your kernel config should also 
enable the modules `SYSFS trigger` with `CONFIG_IIO_SYSFS_TRIGGER` and
`High resolution timer trigger` with `CONFIG_IIO_HRTIMER_TRIGGER`.
Both are under `Linux Kernel Configuration ─> Device Drivers ─> Industrial I/O support ─> Triggers - standalone`.

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

### <a name="bazzite"></a>Bazzite
Handheld Daemon comes pre-installed on Bazzite and updates along-side the system.
The latest version of Handheld Daemon becomes available at the latest the next
day after release, and can be managed through the Bazzite updater.
In addition, Bazzite contains all the required patches for the Handheld Daemon
supported devices, so it is the recommended distro to use Handheld Daemon with.

After install, you can use `ujust` to install Decky and the Handheld Daemon Decky
plugin with the commands `ujust get-decky`, `ujust get-hhd-decky`.

If you need to use a different Handheld Daemon version or a custom one, the 
install steps do not currently work for Bazzite, but this will be fixed in the future.
Essentially, a new service file needs to be written for Bazzite that contains the
correct home path (`/var/home`) and then you can disable the built-in version
service and use the new one instead.

### ❄️ NixOS (experimental)
Update the `nixpkgs.url` input in your flake to point at [the PR](https://github.com/NixOS/nixpkgs/pull/277661/) branch:

```nix
  inputs = {
    nixpkgs.url = "github:appsforartists/nixpkgs/handheld-daemon";
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

## Frequently Asked Questions (FAQ)
### What does the current version of HHD do?

The current version of HHD maps the x-input mode of the Legion Go controllers to
a DualSense 5 Edge controller, which allows using all of the controller
functions. In addition, it adds support for the Steam powerbutton action, so you
get a wink when going to sleep mode.

When the controllers are not in x-input mode, HHD adds a shortcuts device so
that combos such as Steam and QAM keep working.

### Steam reports a Legion Controller and a Shortcuts controller instead of a PS5
The Legion controllers have multiple modes (namely x-input, d-input, dual d-input,
and FPS).
HHD only remaps the x-input mode of the controllers.
You can cycle through the modes with Legion L + RB.

X-input and d-input refer to the protocol the controllers operate in.
Both are legacy protocols introduced in the mid-2000s and are included for hardware
support reasons.

X-input is a USB controller protocol introduced with the xbox 360 controller and 
is widely supported.
Direct input is a competing protocol that works based on USB HID.
Both work the same.
The only difference between them is that d-input has discrete triggers for some
reason, and some games read the button order wrong.

X-input requires a special udev rule to work, see below.

### Other Legion Go gamepad modes
Handheld Daemon remaps the x-input mode of the Legion Go controllers into a PS5 controller.
All other modes function as normal.
In addition, Handheld Daemon adds a shortcuts device that allows remapping the back buttons
and all Legion L, R + button combinations into shortcuts that will work accross
all modes.

### I can not see any Legion Controllers controllers before or after installing
Your kernel needs to know to use the `xpad` driver for the Legion Go's
controllers.

This is expected to be included in a future Linux kernel, so it is not included
by default by HHD.

In the mean time, [apply the patch](https://github.com/torvalds/linux/compare/master...appsforartists:linux:legion-go-controllers.patch), or add a `udev`
rule:

#### `/etc/udev/rules.d/95-hhd.rules`
```bash
# Enable xpad for the Legion Go controllers
ATTRS{idVendor}=="17ef", ATTRS{idProduct}=="6182", RUN+="/sbin/modprobe xpad" RUN+="/bin/sh -c 'echo 17ef 6182 > /sys/bus/usb/drivers/xpad/new_id'"
```

You will see the following in the HHD logs (`sudo systemctl status hhd@$(whoami)`)
if you are missing the `xpad` rule.

```
              ERROR    Device with the following not found:
                       Vendor ID: ['17ef']
                       Product ID: ['6182']
                       Name: ['Generic X-Box pad']
```

### Yuzu does not work with the PS5 controller
See above.
Use yuzu controller settings to select the DualSense controller and disable
Steam Input.

### Freezing Gyro
The gyro used for the PS5 controller is found in the display.
It may freeze occasionally. This is due to the accelerometer driver being
designed to be polled at 5hz, not 100hz.
If that is the case, you need to reboot.

The gyro may exhibit stutters when being polled by `iio-sensor-proxy` to determine
screen orientation.
However, a udev rule that is installed by default disables this.

If you do not need gyro support, you should disable it for a .2% cpu utilisation
reduction.

### No screen autorotation after install
HHD includes a udev rule that disables screen autorotation, because it interferes
with gyro support.
This is only done specifically to the accelerometer of the Legion Go.
If you do not need gyro, you can do the local install and modify
`83-hhd.rules` to remove that rule.
The gyro will freeze and will be unusable after that.

### Touchpad Behavior is different after install/is not part of dualsense
By default, in the Legion Go the handheld daemon uses a virtual touchpad
with proper left/right clicks, which work in gamescope.
If you use your device outside gamescope and find this problematic, switch
`Touchpad Emulation` to `Disabled`.
If you want to use your touchpad for steam input, set the option to `Controller`
and use the `Right Touchpad` under steam.

### HandyGCCS
HHD replicates all functionality of HandyGCCS for the Legion Go, so it is not
required. In addition, it will break HHD by hiding the controller.
You should uninstall it with `sudo pacman -R handygccs-git`.

You will see the following in the HHD logs (`sudo systemctl status hhd@$(whoami)`) 
if HandyGCCS is enabled.
```
              ERROR    Device with the following not found: 
                       Vendor ID: ['17ef']
                       Product ID: ['6182']
                       Name: ['Generic X-Box pad']
```

### Buttons are mapped incorrectly
Buttons mapped in Legion Space will carry over to Linux.
This includes both back buttons and legion swap.
You can reset each controller by holding Legion R + RT + RB, Legion L + LT + LB.
However, we do not know how to reset the Legion Space legion button swap at
this point, so you need to use Legion Space for that.

Another set of obscure issues occur depending on how apps hook to the Dualsense controller.
Certain versions of gamescope and certain games do not support the edge controller,
so switch to `Dualsense` or `Xbox` emulation modes if you are having issues.

If Steam itself is broken and can not see the controllers properly (e.g., you
can not see led/gyro settings or the Edge controller mapping is wrong), you
should update your distribution and if that does not fix it consider re-installing.
There are certain gamescope/distro issues that cause this and we are unsure of
the cause at this moment.
ChimeraOS 44 and certain versions of Nobara 38 and 39 have this issue.

### Disabling Dualsense touchpad
The Dualsense touchpad may interfere with games or steam input. 
You can disable it with the following udev rule.
Place it under `/etc/udev/rules.d/99-hhd-playstation-touchpad.rules`
```bash
# Disables all playstation touchpads from use as touchpads.
ACTION=="add|change", KERNEL=="event[0-9]*", ATTRS{name}=="*Wireless Controller Touchpad", ENV{LIBINPUT_IGNORE_DEVICE}="1"
```

## Contributing
Either follow `Automatic Install` or `Manual Local Install` to install the base rules.
Then, clone, optionally install the userspace rules, and run.
```bash
# Clone Handheld Daemon
git clone https://github.com/hhd-dev/hhd
cd hhd
python -m venv venv
source venv/bin/activate
pip install -e .

# Install udev rules to allow running in userspace 
# optional; great for debugging
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/udev/rules.d/83-hhd-user.rules -o /etc/udev/rules.d/83-hhd-user.rules
# Modprobe uhid to avoid rw errors
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/modules-load.d/hhd-user.conf -o /etc/modules-load.d/hhd-user.conf

# You can now run hhd in userspace!
hhd
# Add user when running with sudo
sudo hhd --user $(whoami)
```
