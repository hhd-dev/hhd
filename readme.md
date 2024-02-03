# Adjustor
Home of the Adjustor tdp cli utility.
WIP.

## Development
Install to the same virtual environment as hhd to have Adjustor picked up
as a plugin upon restart, or to its own venv to use independently.
```python
pip install -e .
```

# ALIB Commands
With values for the Legion Go. For TDP, ALIB uses mW, values were divided by 1000.

| Name                  | SMU  | ALIB | Quiet | Balanced | Performance | Custom |
| --------------------- | ---- | ---- | ----- | -------- | ----------- | ------ |
| STAMP Limit           | 0x14 | 0x05 |       |          |             |        |
| Fast Limit            | 0x15 | 0x06 |       |          |             |        |
| Slow Limit            | 0x16 | 0x07 | 15    | 25       | 32          |        |
| Slow Time             | 0x17 | 0x08 |       |          |             |        |
| STAPM Time            | 0x18 | 0x01 |       |          | 200         | 200    |
| TCTL (Temp Target)    | 0x19 | 0x03 | 75    | 90       | 95          |        |
| Skin Temp Power Limit | 0x4a | 0x2e |       |          |             | 30     |
| ??????                | 0x3d | 0x2c |       |          |             | 5098   |
| ??????                | 0x35 | 0x24 |       |          |             | 98     |
| ??????                |      | 0x22 |       |          |             | 12288  |
| ??????                |      |      |       |          |             |        |
| ??????                |      |      |       |          |             |        |

| ??????                |      | 0x32 | 120000 | CPUT 41

The skin temp limit is the temperature that develops along the user
accessible host spot of the device.
| Name                 | SMU  | ALIB | Quiet | Balanced | Performance |
| -------------------- | ---- | ---- | ----- | -------- | ----------- |
| APU Skin Temp Limit  | 0x33 | 0x22 |       |          |             |
| DGPU Skin Temp Limit | 0x34 | 0x23 |       |          |             |

PROCHOT Ramp controls the overheating behavior, in the case tctl was pushed
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