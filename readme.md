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

## License
An open source license will be chosen in the following days.
It will probably be the Apache license, so if that affects your use case reach
out for feedback.