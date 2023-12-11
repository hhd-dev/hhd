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
User accessible installation is a WIP.
Right now, HHD is a fully functional python package you can install
with `pip install .` if you clone the repository, and the required
rules for it to run without root permissions can be found in the
`usr` director.