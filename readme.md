# Handheld Daemon (HHD)
Handheld Daemon is a project that aims to provide utilities for managing handheld
devices.
With features ranging from TDP controls, to controller remappings, and gamescope 
session management.
This is done through a plugin system, and a dbus daemon, which will expose the
settings of the plugins in a UI agnostic way.

For the time being, the daemon is not d-bus based, and relies on static configuration
stored on `~/.config/hhd`.
The current version contains a fully functional Dual Sense 5 Edge emulator for
the Legion Go (including touchpad, gyro, and LED support).
It is the aim of this project to provide generic hid-based emulators for most
mainstream controllers (xbox Elite, DS4, DS5, Joycons), so that users of devices
can pick the best target for their device and its controls, which may change
depending on the game.

*Current Features*:
- Fully functional Dual Sense 5 Emulator (Legion Go)
    - All buttons supported
    - Rumble feedback
    - Touchpad support (steam input as well)
    - LED remapping
- Power Button plugin
    - Short press makes steam deck sleep
    - Long press opens steam power menu

*Planned Features (in that order)*:
- Steam Deck controller emulation
  - No weird glyphs
- TDP Plugin (Legion Go)
  - Will provide parity with Legion Space, hardware is already reverse engineered
- d-Bus based Configuration
  - Right now, functionality can be tweaked through config files
    - Not ideal for a portable device
  - A d-Bus daemon and a plugin system will allow safe, polkit based
    access to hardware configuration.
- High-end Over/Downclocking Utility for Ryzen processors
  - By hooking into the manufacturer ACPI API of the Ryzen platform,
    it will expose all TDP related parameters manufacturers have access to
    when spec'ing laptops.
  - RyzenAdj Successor
    - No memory-relaxed requirement
    - Safer, as it is the method used by manufacturers
        (provided you stay within limits).
  - May require DSDT patch on boot, TBD.


## Installation Instructions
You can install the latest stable version of `hhd` from AUR or PiPy.

### ChimeraOS
ChimeraOS does not ship with `gcc` to compile hhd dependencies and the functionality
of `handygccs` which fixes the QAM button by default conflicts with hhd.
The easiest way to install is to unlock the filesystem, install hhd, and remove
handygccs.

```bash
# Unlock filesystem
sudo frzr-unlock

# Run installer
sudo pacman -S base-devel
sudo pikaur -S hhd
sudo pacman -R handygccs-git

# Enable and reboot
sudo systemctl enable hhd@$(whoami)
sudo reboot
```

Then, repeat every time you update Chimera. As a bonus, you will get new HHD
features as well 😊.

#### Uninstall
Just run the steps in reverse or switch to a locked Chimera version.
```bash
sudo systemctl disable hhd@$(whoami)

sudo pikaur -S handygccs-git
sudo pacman -R hhd

sudo systemctl enable handygccs
sudo reboot
```

### PyPi Based installation (Nobara/Read only fs)
If you have a read only fs or are on a fedora based system, you may opt to install
a local version of hhd.
```bash
# (nobara) Install Python Headers since evdev has no wheels
# and nobara does not ship them (but arch does)
sudo dnf install python-devel

# Install hhd to ~/.local/share/hhd
mkdir -p ~/.local/share/hhd
cd ~/.local/share/hhd

python -m venv venv
source venv/bin/activate
pip install hhd

# Install udev rules and create a service file
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/udev/rules.d/83-hhd.rules -o /etc/udev/rules.d/83-hhd.rules 
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/systemd/system/hhd_local%40.service -o /etc/systemd/system/hhd_local@.service

# Start service and reboot
sudo systemctl enable hhd_local@$(whoami)
sudo reboot
```

#### Update Instructions
Of course, you will want to update HHD to catch up to latest features
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

> The above should work on read only fs, provided the /etc directory is not read
> only.

### Arch-based Installation (AUR)
```bash
# Install using your AUR package manager
sudo pikaur -S hhd
sudo yay -S hhd
sudo pacman -S hhd # manjaro only

# Enable and reboot
sudo systemctl enable hhd@$(whoami)
sudo reboot
```

But I dont want to reboot...
```bash
# Reload hhd's udev rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# Restart iio-proxy-service to stop it
# from polling the accelerometer
sudo systemctl restart iio-sensor-proxy
# Start the service for your user
sudo systemctl start hhd@$(whoami)
```

> To ensure the gyro of the Legion Go and other devices with AMD SFH runs smoothly, 
> a udev rule is included that disables the use of the accelerometer by the 
> system (e.g., iio-sensor-proxy).
> This limitation will be lifted in the future, if a new driver is written for
> amd-sfh.

#### Updating/Uninstalling in Arch
HHD will update automatically with your system from then on, or you can update it
manually with your AUR package manager.
To uninstall, just uninstall the package and reboot.

```bash
# Update using your AUR package manager
sudo pikaur -S hhd
sudo yay -S hhd
sudo pacman -S hhd # manjaro only

# Remove to uninstall
sudo pacman -R hhd
sudo reboot
```

## Configuring HHD
The reason you added your username to the hhd service was to bind the hhd daemon
to your user.
This allows HHD to add configuration files with appropriate permissions to your
user dir, which is the following:
```bash
~/.config/hhd
```

Configuration for plugins will appear in the plugins directory.
Only the legion controller plugin has configuration options for now.
```bash
~/.config/hhd/plugins
```

Restart `hhd` to reload the configurations afterwards.
```bash
# Arch
sudo systemctl restart hhd@$(whoami)
# Local install
sudo systemctl restart hhd_local@$(whoami)
```

## Quirks
### Playstation Driver
There is a small touchpad issue with the playstation driver loaded.
Where a cursor might appear when using the touchpad in steam input.
This should be fixed in the latest version.
If not, you can fix it by blacklisting the playstation driver.
However, you will get a lot of issues if you dont exclusively use steam input 
afterwards so do not do it otherwise.
You will not be able to use the touchpad as a touchpad anymore and that is the
only way to wake up the screen in desktop mode.
Games that do not support Dual Sense natively (e.g., wine games) will not have
a correct gamepad profile and will not work either.
```bash
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/modprobe.d/hhd.conf -o /etc/udev/modprobe.d/hhd.conf
```

### Other gamepad modes
HHD remaps the xinput mode of the Legion Go controllers into a DS5 controller.
All other modes function as normal.
In addition, HHD adds a shortcuts device that allows remapping the back buttons
and all Legion L, R + button combinations into shortcuts that will work accross
all modes.

### Freezing Gyro
The gyro used for the DS5 controller is found in the display.
It may freeze occasionally. This is due to the accelerometer driver being
designed to be polled at 5hz, not 100hz.
If that is the case, you need to reboot.

The gyro may exhibit stutters when being polled by `iio-sensor-proxy` to determine
screen orientation.
However, a udev rule that is installed by default disables this.

If you do not need gyro support, you should disable it for a .2% cpu utilisation
reduction.
By default, the accelerometer is disabled for this reason.

You need to set both `gyro` and `gyro-fix` to `False` in the config to disable
gyro support.

### HandyGCCS
HHD replicates all functionality of HandyGCCS for the Legion Go, so it is not
required. In addition, it will break HHD by hiding the controller.
You should uninstall it with `sudo pacman -R handygccs-git`.
```
              ERROR    Device with the following not found:                                                                                                                          evdev.py:122
                       Vendor ID: ['17ef']
                       Product ID: ['6182']
                       Name: ['Generic X-Box pad']
```

## Contributing
You should install from source if you aim to contribute or want to pull from master.
```bash
# Install hhd to ~/.local/share/hhd
mkdir -p ~/.local/share/
git clone https://github.com/antheas/hhd ~/.local/share/hhd

cd ~/.local/share/hhd
python -m venv venv
source venv/bin/activate
pip install -e .

# Install udev rules and create a service file
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/udev/rules.d/83-hhd.rules -o /etc/udev/rules.d/83-hhd.rules 
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/systemd/system/hhd_local%40.service -o /etc/systemd/system/hhd_local@.service

# Install udev rules to allow running in userspace (optional; great for debugging)
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/udev/rules.d/83-hhd-user.rules -o /etc/rules.d/83-hhd-user.rules 
# Modprobe uhid to avoid rw errors
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/modules-load.d/hhd-user.conf -o /etc/modules-load.d/hhd-user.conf

# Reboot
sudo reboot

# You can now run hhd in userspace!
hhd
# Add user when running with sudo
sudo hhd --user $(whoami)
```

## License
An open source license will be chosen in the following days.
It will probably be the Apache license, so if that affects your use case reach
out for feedback.