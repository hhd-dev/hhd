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

### Arch-based Installation
```bash
# For arch
yay -S hhd
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

### PyPi Based installation
If you have a read only fs or are on a fedora based system, you may opt to install
a local version of hhd.
```bash
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
sudo systemctl stop hhd_local@$(whoami)
rm -rf ~/.local/share/hhd
sudo rm /etc/udev/rules.d/83-hhd.rules
sudo rm /etc/systemd/system/hhd_local@.service
# Delete your configuration
rm -r ~/.config/hhd
```

> The above should work on read only fs, provided the /etc directory is not read
> only.

## Configuring HHD
The reason you added your username to the hhd service was to bind the hhd daemon
to your user.
This allows HHD to add configuration files with appropriate permissions to your
user dir, which is the following:
```bash
~/.config/hhd
```

## Quirks
### Playstation Driver
Right now, steam is broken with the playstation driver. You should blacklist the
driver and use steam input instead with DS5.
If not, you will notice issues with the touchpad, and the driver will override
the led configuration.
```bash
sudo curl https://raw.githubusercontent.com/antheas/hhd/master/usr/lib/modprobe.d/hhd.conf -o /etc/udev/modprobe.d/hhd.conf
```

This will mean that outside steam and linux native games, the controller will not
work.
However, when running in any of the other modes legion go supports (dinput, dual dinput,
fps mode), HHD adds a shortcuts device, so they are fully usable.

### Other gamepad modes
HHD remaps the xinput mode of the Legion Go controllers into a DS5 controller.
All other modes function as normal.
In addition, HHD adds a shortcuts device that allows remapping the back buttons
and all Legion L, R + button combinations into shortcuts that will work accross
all modes.

### Freezing Gyro
The gyro used for the DS5 controller is found in the display .
It may freeze occasionally. This is due to the accelerometer driver being
designed to be polled at 5hz, not 100hz.
If that is the case, you should reboot.

The gyro may also freeze when being polled by `iio-sensor-proxy` to determine
screen orientation.
However, a udev rule that is installed by default disables this.

If you do not need gyro support, you should disable it for a .2% cpu utilisation
reduction.
By default, the accelerometer is disabled for this reason.

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
sudo --user $(whoami)
```

## License
An open source license will be chosen in the following days.
It will probably be the Apache license, so if that affects your use case reach
out for feedback.