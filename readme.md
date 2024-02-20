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

In addition, it fully implements Lenovo's WMI protocol for the Legion Go, allowing
setting the TDP, including boosting behavior, without interference from
the Embedded Computer.
As part of the latest Lenovo bios, it also allows for setting a custom fan curve
for the Legion Go.

## AMD TDP Control
Adjustor controls TDP through the Dynamic Power and Thermal Configuration Interface, 
which exposes a superset of the parameters that can be found in 
[RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/), through ACPI.
This vendor function is part of the ACPI ASL library, and provided through the
ALIB method 0x0C.
This means that as long as the kernel module `acpi_call` is loaded, Adjustor
can control TDP in an equivalent way to [RyzenAdj](https://github.dev/FlyGoat/RyzenAdj/).

ALIB does not provide a way for reading the performance metrics table, so 
Adjustor can only write TDP values.
From reverse engineering the Legion Go (see [here](./alib.md)), and seeing how it
interacts with ALIB, it was found that there are at least 10 parameters which control
the method STTv2 and are not part of RyzenAdj or have been documented elsewhere.

## Installation
Installation instructions coming the following days.

## Development
Install to the same virtual environment as hhd to have Adjustor picked up
as a plugin upon restart, or to its own venv to use independently.
```python
pip install -e .
```