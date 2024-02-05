## Frequently Asked Questions (Old)

### What does the current version of Handheld Daemon do?
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
