### Kernel Patches
### LED
For LED support, the following modules are required for Ayaneo and Ayn: 
[ayaneo-platform](https://github.com/ShadowBlip/ayaneo-platform)
driver, and for Ayn, the [ayn-platform](https://github.com/ShadowBlip/ayn-platform).
Provided these drivers are installed and are supported by your device,
LED support will be enabled by default.

### Gyro
Which kernel patch is required will depend on your device's Bosch module.
For the Bosch 260 IMU (most GPD), you will need the 
[bmi260-dkms](https://github.com/hhd-dev/bmi260) driver.
For the Bosch 160 IMU (GPD 6800u) and certain devices, you will need the following bmi160
[kernel patch](https://github.com/pastaq/bmi160-aya-neo/blob/main/bmi160_ayaneo.patch).
Ayaneo Air Plus and Ally use the Bosch 323 and need the patch series from
this repository: [Ally Nobara Fixes](https://github.com/jlobue10/ALLY_Nobara_fixes). 

In addition, for most devices, your kernel config should also 
enable the modules `SYSFS trigger` with `CONFIG_IIO_SYSFS_TRIGGER` and
`High resolution timer trigger` with `CONFIG_IIO_HRTIMER_TRIGGER`.
Both are under `Linux Kernel Configuration ─> Device Drivers ─> Industrial I/O support ─> Triggers - standalone`.

### TDP
For the ROG Ally, an up-to-date kernel is required (6.5+).
For the rest of the devices, acpi_call as a dkms package or kernel patch is
required (included in Bazzite, Nobara, ChimeraOS).