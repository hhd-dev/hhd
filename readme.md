# Adjustor
Home of the Adjustor TDP plugin for Handheld Daemon.
Adjustor currently allows for TDP control of all AMD Handhelds past generation
6### (support is added manually).
Since it integrates with Handheld Daemon, it is available through 
[Decky](https://github.com/hhd-dev/hhd-decky),
and through [hhd-ui](https://github.com/hhd-dev/hhd-ui).

Adjustor implements a reversed engineered version of AMD's vendor function for
setting TDP on demand in Ryzen processors, through ACPI.
This means that it can be used regardless of the current memory policy
or secure-boot/lockdown status (provided the module `acpi_call` is installed.).

For the ROG Ally and Legion Go that have an ACPI/EC implementation for bios and fan curves,
Adjustor uses the manufactuer way for setting TDP.
For the ally, the asus-wmi kernel driver is used to set the tdp and manage the
fan curves.
For the go, Lenovo's WMI methods are called through `acpi_call`, which will hopefully
become part of a driver in the future.

## AMD TDP Control
Adjustor controls TDP through the Dynamic Power and Thermal Configuration Interface
of AMD, which exposes a superset of the parameters that can be currently found in 
[RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/), through ACPI.
This vendor interface is part of the ACPI ASL library, and provided through the
ALIB method 0x0C.
The underlying implementation of the interface is SMU calls.
This means that as long as the kernel module `acpi_call` is loaded, Adjustor
can control TDP in an equivalent way to [RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/).

Right now, Adjustor only implements a subset of useful ALIB parameters that are
well documented.
In addition, ALIB does not provide a way for reading the performance metrics table, 
so Adjustor can only write (not read) TDP values.
From reverse engineering the Legion Go (see [here](./alib.md)), and seeing how it
interacts with ALIB, it was found that there are at least 10 parameters which control
the method STTv2 and are not part of RyzenAdj or have been documented elsewhere.

## Installation
Adjustor is available on [AUR](https://aur.archlinux.org/packages/adjustor)
and provided Handheld Daemon has been installed through 
[AUR](https://aur.archlinux.org/packages/hhd) too, it will load it automatically
on restart.
COPR coming soon.

Alternatively, on a local install of Handheld Daemon you may:
```bash
~/.local/share/hhd/venv/bin/pip install --upgrade adjustor
```
However, the autoupdater in Handheld Daemon does not support updating yet.

## Development
Install to the same virtual environment as hhd to have Adjustor picked up
as a plugin upon restart, or to its own venv to use independently.
```python
pip install -e .
```

# License
Adjustor is licensed under THE GNU GPLv3+. See LICENSE for details.
Versions prior to and excluding 2.0.0 are licensed using MIT.