### Kernel Patches
### LED
For LED support, the following modules are required for Ayaneo and Ayn: 
[ayaneo-platform](https://github.com/ShadowBlip/ayaneo-platform)
driver, and for Ayn, the [ayn-platform](https://github.com/ShadowBlip/ayn-platform).
Provided these drivers are installed and are supported by your device,
LED support will be enabled by default.

### Gyro
For the Bosch 260 IMU (most GPD devices), you will need the 
[bmi260-dkms](https://github.com/hhd-dev/bmi260) driver.
Otherwise, all kernel patches are on the upstream kernel as of 6.9.

In addition, for most devices, your kernel config should also 
enable the modules `SYSFS trigger` with `CONFIG_IIO_SYSFS_TRIGGER` and
`High resolution timer trigger` with `CONFIG_IIO_HRTIMER_TRIGGER`.
Both are under `Linux Kernel Configuration ─> Device Drivers ─> Industrial I/O support ─> Triggers - standalone`.
The Arch kernel config includes them, but the default fedora config does not
include `CONFIG_IIO_HRTIMER_TRIGGER`.

### TDP
For the ROG Ally, an up-to-date kernel is required (6.5+).
For Ally X, 6.11+ with `amd-pmf` blocked is required (see [here](https://github.com/hhd-dev/hhd/issues/95#issuecomment-2336425436)).
For the rest of the devices, `acpi_call` as a dkms package or kernel patch is
required (included in Bazzite, Nobara, ChimeraOS).

### SDL Evdev Gyro emulation
For SDL Evdev emulation to work, uinput needs to support setting the uniq attribute.
This is done using this out-of-tree 
[kernel patch](https://github.com/hhd-dev/linux-handheld/blob/master/6.6/uinput.patch).

### Gyro (prior to 6.9)
Which kernel patch is required will depend on your device's Bosch module.
For the Bosch 160 IMU (GPD 6800u) and certain devices, you will need the following bmi160
[kernel patch](https://github.com/pastaq/bmi160-aya-neo/blob/main/bmi160_ayaneo.patch),
which became [part of the kernel on 6.9](https://github.com/torvalds/linux/commit/ca2f16c315683d9922445b59a738f6e4c168d54d).
Ayaneo Air Plus and Ally use the Bosch 323, which 
[became part of the kernel on 6.9](https://github.com/torvalds/linux/commit/3cc5ebd3a2d6247aeba81873d6b040d5d87f7db1).
For older kernels, a patch series can be found in this repository: 
[Ally Nobara Fixes](https://github.com/jlobue10/ALLY_Nobara_fixes).