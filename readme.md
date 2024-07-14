# Adjustor
Home of the Adjustor TDP plugin for Handheld Daemon.
Adjustor currently allows for TDP control of all AMD Handhelds past generation
6### (support is added manually).
Intel is not currently supported.
For installation and usage, see the [main readme](https://github.com/hhd-dev/hhd).
Adjustor supports all handhelds in the Handheld Daemon supported list,
except intel handhelds and older prior to 6XXX AMD handhelds.

> [!IMPORTANT]
> Adjustor supports per-device TDP values but its database is not fully featured
> yet, with a fallback to 0-30W for missing devices
> that use the ALIB driver. Use common sense while on battery and reference
> your manufacturer's spec sheet. Open an issue so your device can have correct
> limits.

## TDP Control
For the ROG Ally, Ally X and Legion Go that have an ACPI/EC implementation for 
bios and fan curves,
Adjustor uses the manufactuer functions for setting TDP.
For the Allys, the asus-wmi kernel driver is used to set the tdp and manage the
fan curves.
For the Go, Lenovo's WMI methods are called through `acpi_call`, which will hopefully
become part of a driver in the future.

For other devices, Adjustor implements a reverse engineered version of AMD's 
vendor function for setting TDP on demand in Ryzen processors, through ACPI.
This means that it can be used regardless of the current memory policy
or secure-boot/lockdown status (provided the module `acpi_call` is installed.).
For more, see [AMD TDP Control Details](#amd-tdp).

In all cases, there are checks to ensure that the TDP is within the safe range
of the processors.

## Energy Management
Adjustor can also manage the energy profile of the processor, by setting EPP
and proper frequency values.
After we transitioned people away from Decky plugins (which had some governor controls)
to using Handheld Daemon for TDP, we found that Power Profiles Daemon (PPD) 
would use aggressive CPU values.
These values are optimized for devices that have a dedicated power budget for the CPU
(e.g., laptops, desktops), which caused issues with handhelds.

For example, the balanced PPD profile would set EPP to balance_performance and
enable CPU boost, which would increase the draw of the CPU during gaming by 2W
and idle CPU temperature from 55C to around 70C.
The performance profile would switch the governor to performance and set EPP to 
performance, which would exacerbate this problem.
In addition, the KDE and Gnome sliders were confusing for users, as they did not
affect TDP (which is mostly determined by the GPU which is unaffected by PPD).

Starting with version 3.1, when PPD is not present, Adjustor will manage the
EPP, boost, and minimum frequency of the processor itself.
By default, this is automatic, with sane values for handhelds: 
 - governor is always powersave
 - EPP is power or balance_power
 - boost is enabled only on high TDPs
 - On high TDPs, minimum frequency is ~1Ghz (min. nonlinear). Was found to help frame
    pacing on the Ally and VRR displays.

The user can also tweak the values themselves, as certain games have a preference
for high CPU utilization.
During testing, it was found that disabling CPU boost and lowering EPP results
in a modest 10 fps increase on high TDPs and around 1W of less power consumption 
on non-demanding games.

In addition, Adjustor will emulate the dbus protocol of PPD, so that the sliders in
KDE Powerdevil and Gnome shell work as expected, and make them control the
TDP range instead of CPU values (which is the user's expectation).
Of course, depending on TDP and user preference, the CPU governor values will be set
accordingly.

## AMD TDP Control Details<a name="amd-tdp"></a>
Adjustor controls TDP through the Dynamic Power and Thermal Configuration Interface
of AMD, which exposes a superset of the parameters that can be currently found in 
[RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/), through ACPI.
This vendor interface is part of the ACPI ASL library, and provided through the
ALIB method 0x0C.
The underlying implementation of the interface is SMU calls.
This means that as long as the kernel module `acpi_call` is loaded, Adjustor
can control TDP in an equivalent way to [RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/).

The ABI of this vendor function (as it is provided to manufacturers) can be 
considered mostly stable, so little work is needed between subsequent 
processor generations (it has not changed since 6XXX; previous
generations only had additions).
Of course, support for processors is only added after the ACPI bindings have
been reviewed, to avoid surprises.
Both the Ally and Legion Go use this function, in the exact same way, so setting
TDP with it is very stable, and we have had no reported crashes.
It should not be used (and is not used) with those devices, however, as the 
manufacturer functions will interfere.

Unfortunately for devices that do have an ACPI/EC implementation for TDP, there
is no official way of setting TDP on demand, either on Linux or Windows, with
TDP remaining to what is set on the BIOS level.
Vendors that offer this functionality without an ACPI implementation
(such as Ayaneo), use RyzenAdj on Windows (can be seen on the Ayaneo Space directory).
This is not ideal, as RyzenAdj does not hold a lock while performing
SMU calls, and may perform them at the same time as the GPU driver which can
confuse it and cause a kernel panic.
We have recorded crashes with it both on Windows and Linux with implementations 
which set TDP at a frequent interval (5-10s; unrelated
to this project; as neither AutoTDP or RyzenAdj are used).

Right now, Adjustor only implements a subset of useful ALIB parameters that are
well documented.
In addition, ALIB does not provide a way for reading the performance metrics table,
which is meant for debugging, so Adjustor can only write (not read) TDP values.
For that purpose, refer to [RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/).
From reverse engineering the Legion Go (see [here](./alib.md)), and seeing how it
interacts with ALIB, it was found that there are at least 10 parameters which control
the method STTv2 and are not part of RyzenAdj or have been documented elsewhere.

## Installation
Adjustor is installed as part of Handheld Daemon now, so follow the instructions
at [the main repository](https://github.com/hhd-dev/hhd#installation-instructions).
It is available in [AUR](https://aur.archlinux.org/packages/adjustor), 
[COPR](https://copr.fedorainfracloud.org/coprs/hhd-dev/hhd/package/adjustor/), 
and [PyPi](https://github.com/hhd-dev/adjustor/issues).

## Development
Install to the same virtual environment as Handheld Daemon to have Adjustor picked up
as a plugin upon restart, or to its own virtual environment to use independently.
```python
pip install -e .
```

# License
Adjustor is licensed under THE GNU GPLv3+. See LICENSE for details.
Versions prior to and excluding 2.0.0 are licensed using MIT.