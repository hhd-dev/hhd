# Adjustor
Home of the Adjustor tdp cli utility.
WIP.

## Development
Install to the same virtual environment as hhd to have Adjustor picked up
as a plugin upon restart, or to its own venv to use independently.
```python
pip install -e .
```

# ALIB/SMU Commands
Below are the most important TDP SMU commands.

| Name                  | SMU  | ALIB |
| --------------------- | ---- | ---- |
| STAMP Limit           | 0x14 | 0x05 |
| Fast Limit            | 0x15 | 0x06 |
| Slow Limit            | 0x16 | 0x07 |
| Slow Time             | 0x17 | 0x08 |
| STAPM Time            | 0x18 | 0x01 |
| TCTL (Temp Target)    | 0x19 | 0x03 |
| Skin Temp Power Limit | 0x4a | 0x2e |
| ??????                | 0x3d | 0x2c |
| ??????                | 0x35 | 0x24 |
| ??????                | 0x33 | 0x22 |
| ??????                | 0x21 | 0x32 |

The skin temp limit is the temperature that develops along the user
accessible host spot of the device.

| Name                 | SMU  | ALIB | Quiet | Balanced | Performance |
| -------------------- | ---- | ---- | ----- | -------- | ----------- |
| APU Skin Temp Limit  | 0x33 | 0x22 |       |          |             |
| DGPU Skin Temp Limit | 0x34 | 0x23 |       |          |             |

PROCHOT Ramp controls the overheating behavior, in the case TCTL was pushed
too high and a jitter caused a power issue.
It is unclear what APU Slow limit controls.

| Name           | SMU  | ALIB |
| -------------- | ---- | ---- |
| PROCHOT Ramp   | 0x1f | 0x09 |
| APU Slow Limit | 0x23 | 0x13 |

Manufacturer set in Amps, can damage the device by overheating the VRMs.
| Name                | SMU  | ALIB |
| ------------------- | ---- | ---- |
| VRM Current         | 0x1a | 0x0b |
| VRM SOC Current     | 0x1b | 0x0e |
| VRM MAX Current     | 0x1e | 0x0d |
| VRM SOC Max Current | 0x1d | 0x11 |

????
| Name      | SMU  | ALIB |
| --------- | ---- | ---- |
| GFX CLK   | 0x89 | NA   |
| COALL (?) | 0x4c | NA   |
| COPER (?) | 0x4b | NA   |
| COGFX (?) | 0xb7 | NA   |

AC/DC Configuration
| Name            | SMU  | ALIB |
| --------------- | ---- | ---- |
| Power Saving    | 0x12 | *    |
| Max Performance | 0x11 | *    |

# Legion Go ALIB Binds
The Legion Go ACPI features 2 TDP functions, one that is called 
when changing power modes (such as with Legion L + Y), and one that
is called when the device enters a different power state, such as being
plugged in.

Extreme mode is not available currently.

## AC/DC change AC Values
When the device gets plugged in, the embedded processor calls method `_Q30` and
sets the following:

| Name                  | SMU  | ALIB | Quiet | Balanced | Performance | Extreme |
| --------------------- | ---- | ---- | ----- | -------- | ----------- | ------- |
| Slow Limit            | 0x16 | 0x07 | 15    | 25       | 32          |         |
| TCTL (Temp Target)    | 0x19 | 0x03 | 75    | 90       | 95          |         |
| STAPM Time            | 0x18 | 0x01 |       |          | 200s        | 200s    |
| Skin Temp Power Limit | 0x4a | 0x2e |       |          |             | 30      |
| ??????                | 0x3d | 0x2c |       |          |             | 0x13EA  |
| ??????                | 0x35 | 0x24 |       |          |             | 0x62    |
| ??????                | 0x33 | 0x22 |       |          |             | 0x3000  |

If CPUT is 0x41, ALIB 0x32 is set to 0x0001D4C0.

## AC/DC change DC Values
When the device is on battery, likewise with the following:

| Name                  | SMU  | ALIB | Quiet | Balanced | Performance | Extreme |
| --------------------- | ---- | ---- | ----- | -------- | ----------- | ------- |
| Slow Limit            | 0x16 | 0x07 | 8     | 15       | 20          |         |
| TCTL (Temp Target)    | 0x19 | 0x03 | 70    | 80       | 85          |         |
| STAPM Time            | 0x18 | 0x01 |       |          | 150s        | 100s    |
| Skin Temp Power Limit | 0x4a | 0x2e |       |          |             | 25      |
| ??????                | 0x3d | 0x2c |       |          |             | 0x14EA  |
| ??????                | 0x35 | 0x24 |       |          |             | 0x4F    |
| ??????                | 0x33 | 0x22 |       |          |             | 0x2E00  |

If CPUT is 0x41, ALIB 0x32 is set to 0x00012CC8.

## Custom mode set values
If the GO is in custom mode, `_Q30` does not apply.
A function `_Q3D` sets the following:

| Name                  | SMU  | ALIB | Custom |
| --------------------- | ---- | ---- | ------ |
| Fast Limit            | 0x15 | 0x06 | CFTP   |
| Slow Limit            | 0x16 | 0x07 | CSTP   |
| STAPM Limit           | 0x14 | 0x05 | CTDP   |
| Skin Temp Power Limit | 0x4a | 0x2e | CTDP   |

The values are reset to 0 when setting a mode other than custom.
When going back to custom, this function sets defaults for them.
CTDP is set to 30W on AC and 25W on DC.
CFTP is set to 41W, and CSTP is set to 32W.

This means that currently on windows, CSTP is always 32W, which means that if
the temp target is not reached, it will keep boosting at around 32W and it will
ignore CTDP or skin temp power limit.
STAMP limit is not used on STT.

## SSFM
The main TDP function of the GO is `SSFM` and it is called when changing power
modes in Legion Space, pressing Legion L + Y, or during boot.

| Name                  | SMU  | ALIB |
| --------------------- | ---- | ---- |
| STAMP Limit           | 0x14 | 0x05 |
| Fast Limit            | 0x15 | 0x06 |
| Slow Limit            | 0x16 | 0x07 |
| Slow Time             | 0x17 | 0x08 |
| STAPM Time            | 0x18 | 0x01 |
| TCTL (Temp Target)    | 0x19 | 0x03 |
| Skin Temp Power Limit | 0x4a | 0x2e |
| VRM Current           | 0x1a | 0x0b |
| ??????                | 0x3d | 0x2c |
| ??????                | 0x35 | 0x24 |
| ??????                | 0x33 | 0x22 |
| ??????                | 0x21 | 0x32 |

| ??????                | |  |

DPC1 = 0x05
DPC2 = 0x07
DPC3 = 0x06
DPC4 = 0x01
DPC5 = 0x08
DPC8 = 0x03
DPC9 = 0x32
DPCC = 0x2C
DC11 = 0x2E
DC10 = 0x22
DPCE = 0x24
DPC6 = 0x0B

DPC7 = 0x0C
DPCA = 0x26
DPCB = 0x27
DPCD = 0x20
DPCF = 0x25
SSZE = 0x57