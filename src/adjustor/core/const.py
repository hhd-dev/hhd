from typing import TypedDict

from .alib import A, D, DeviceParams, AlibParams


class DevicePreset(TypedDict):
    tdp_limit: int
    slow_limit: int
    fast_limit: int
    slow_time: int
    stapm_time: int
    temp_target: int
    fan_curve: dict[int, float] | None


class DevideProfile(TypedDict):
    quiet: DevicePreset
    balanced: DevicePreset
    performance: DevicePreset
    # Turbo is custom with max tdp values
    turbo: DevicePreset

    platform_profile_map: dict[str, int]
    ppd_balanced_min: int
    ppd_performance_min: int

    alib: dict[str, AlibParams]
    dev: dict[str, DeviceParams]


class DeviceTDP(TypedDict):
    quiet: int
    balanced_min: int
    balanced: int
    performance_min: int
    performance: int
    performance_dc: int | None
    min_tdp: int
    max_tdp_dc: int | None
    max_tdp: int
    max_tdp_boost: int | None
    max_tdp_oc: int
    supports_cycle: bool | None


class DeviceTDPv2(TypedDict):
    quiet: tuple[int, int, int | None]
    balanced_min: int
    balanced: tuple[int, int, int | None]
    performance_min: int
    performance: tuple[int, int, int | None]
    performance_dc: int | None
    min_tdp: int
    max_tdp_dc: int | None
    max_tdp: int
    max_tdp_oc: int
    max_tdp_sppt: int | None
    max_tdp_fppt: int | None
    supports_cycle: bool | None


# internal name for ppd, platform_profile choices, min TDP for
# profile to apply, tdp target to apply when selecting profile
ENERGY_MAP = [
    ("power", ["low-power", "quiet"], 0, 8),
    ("balanced", ["balanced"], 13, 15),
    ("performance", ["performance"], 20, 25),
]
ENERGY_MAP_18W = [
    ("low-power", ["low-power", "quiet"], 0, 5),
    ("balanced", ["balanced"], 8, 12),
    ("performance", ["performance"], 13, 18),
]

ALIB_PARAMS = {
    # TDPs
    "stapm_limit": A(0x05, 0, 54, 1000),
    "fast_limit": A(0x06, 0, 54, 1000),
    "slow_limit": A(0x07, 0, 54, 1000),
    "skin_limit": A(0x2E, 0, 54, 1000),
    # Times
    "slow_time": A(0x08, 0, 30),
    "stapm_time": A(0x01, 0, 300),
    # Temp
    "temp_target": A(0x03, 0, 105),
}

ALIB_PARAMS_5040: dict[str, AlibParams] = ALIB_PARAMS
ALIB_PARAMS_7040: dict[str, AlibParams] = ALIB_PARAMS
ALIB_PARAMS_6040: dict[str, AlibParams] = ALIB_PARAMS
ALIB_PARAMS_8040: dict[str, AlibParams] = ALIB_PARAMS
ALIB_PARAMS_HX370: dict[str, AlibParams] = ALIB_PARAMS

DEV_PARAMS_30W: dict[str, DeviceParams] = {
    "stapm_limit": D(0, 4, 15, 30, 40),
    "skin_limit": D(0, 4, 15, 30, 40),
    "slow_limit": D(0, 4, 20, 32, 43),
    "fast_limit": D(0, 4, 25, 41, 50),
    # Times
    "slow_time": D(5, 5, 10, 10, 10),
    "stapm_time": D(100, 100, 100, 200, 200),
    # Temp
    "temp_target": D(60, 70, 85, 90, 100),
}

DEV_PARAMS_18W: dict[str, DeviceParams] = {
    "stapm_limit": D(0, 5, 15, 18, 22),
    "skin_limit": D(0, 5, 15, 18, 22),
    "slow_limit": D(0, 5, 15, 18, 22),
    "fast_limit": D(0, 5, 15, 20, 25),
    # Times
    "slow_time": D(5, 5, 10, 10, 10),
    "stapm_time": D(100, 100, 100, 200, 200),
    # Temp
    "temp_target": D(60, 70, 85, 90, 100),
}
DEV_PARAMS_25W: dict[str, DeviceParams] = {
    "stapm_limit": D(0, 4, 15, 25, 32),
    "skin_limit": D(0, 4, 15, 25, 32),
    "slow_limit": D(0, 4, 20, 27, 35),
    "fast_limit": D(0, 4, 25, 30, 37),
    # Times
    "slow_time": D(5, 5, 10, 10, 10),
    "stapm_time": D(100, 100, 100, 200, 200),
    # Temp
    "temp_target": D(60, 70, 85, 90, 100),
}
DEV_PARAMS_28W: dict[str, DeviceParams] = {
    "stapm_limit": D(0, 4, 15, 28, 32),
    "skin_limit": D(0, 4, 15, 28, 32),
    "slow_limit": D(0, 4, 20, 30, 35),
    "fast_limit": D(0, 4, 25, 32, 37),
    # Times
    "slow_time": D(5, 5, 10, 10, 10),
    "stapm_time": D(100, 100, 100, 200, 200),
    # Temp
    "temp_target": D(60, 70, 85, 90, 100),
}

DEV_PARAMS_5000: dict[str, DeviceParams] = DEV_PARAMS_25W
DEV_PARAMS_6000: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_7040: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_8040: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_HX370: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_LEGO = DEV_PARAMS_30W

DEV_DATA: dict[
    str,
    tuple[
        dict[str, DeviceParams],
        dict[str, AlibParams],
        bool,
        list[tuple[str, list[str], int, int]],
    ],
] = {
    "NEO-01": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False, ENERGY_MAP),
    "V3": (DEV_PARAMS_28W, ALIB_PARAMS_8040, False, ENERGY_MAP),
    "83E1": (DEV_PARAMS_LEGO, ALIB_PARAMS_7040, False, ENERGY_MAP),
    "ONEXPLAYER F1Pro": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, False, ENERGY_MAP),
    "ONEXPLAYER F1 EVA-02": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, False, ENERGY_MAP),
    # GPD Devices are 28W max
    "G1618-04": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False, ENERGY_MAP),
    "G1617-01": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False, ENERGY_MAP),
    "G1619-04": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False, ENERGY_MAP),
    "G1619-05": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False, ENERGY_MAP),
}

CPU_DATA: dict[
    str,
    tuple[
        dict[str, DeviceParams],
        dict[str, AlibParams],
        list[tuple[str, list[str], int, int]],
    ],
] = {
    "AMD Ryzen Z1 Extreme": (DEV_PARAMS_7040, ALIB_PARAMS_7040, ENERGY_MAP),
    "AMD Ryzen Z1": (DEV_PARAMS_7040, ALIB_PARAMS_7040, ENERGY_MAP),
    # Ayaneo AIR Pro, max is 18W
    "AMD Ryzen 5 5560U": (DEV_PARAMS_18W, ALIB_PARAMS_5040, ENERGY_MAP_18W),
    # 28W works fine, 30W is pushing it
    "AMD Ryzen 7 5700U": (DEV_PARAMS_5000, ALIB_PARAMS_5040, ENERGY_MAP),
    "AMD Ryzen 7 5800U": (DEV_PARAMS_5000, ALIB_PARAMS_5040, ENERGY_MAP),
    # GPD Win 4
    # model name    : AMD Ryzen 7 6800U with Radeon Graphics
    "AMD Ryzen 7 6800U": (DEV_PARAMS_6000, ALIB_PARAMS_6040, ENERGY_MAP),
    "AMD Ryzen 7 7840U": (DEV_PARAMS_7040, ALIB_PARAMS_7040, ENERGY_MAP),
    "AMD Ryzen 7 8840U": (DEV_PARAMS_8040, ALIB_PARAMS_8040, ENERGY_MAP),
    # AMD Athlon Silver 3050e (Win600, will it support tdp?)
    "AMD Ryzen AI 9 HX 370": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, ENERGY_MAP),
    "AMD Ryzen AI HX 360": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, ENERGY_MAP),
}

ALLY_DATA: DeviceTDP = {
    "quiet": 10,
    "balanced_min": 13,
    "balanced": 15,
    "performance_min": 20,
    "performance_dc": 25,
    "performance": 30,
    "min_tdp": 5,
    "max_tdp_dc": 25,
    "max_tdp": 30,
    "max_tdp_oc": 50,
    "max_tdp_boost": None,
    "supports_cycle": True,
}

ALLYX_DATA: DeviceTDP = {
    "quiet": 13,
    "balanced_min": 15,
    "balanced": 17,
    "performance_min": 22,
    "performance_dc": 25,
    "performance": 30,
    "min_tdp": 5,
    "max_tdp_dc": 25,
    "max_tdp": 30,
    "max_tdp_oc": 50,
    "max_tdp_boost": None,
    "supports_cycle": True,
}

Z1_DATA: DeviceTDP = {
    "quiet": 40,
    "balanced_min": 42,
    "balanced": 45,
    "performance_min": 50,
    "performance_dc": 54,
    "performance": 65,
    "min_tdp": 5,
    "max_tdp_dc": 54,
    "max_tdp": 65,
    "max_tdp_oc": 90,
    "max_tdp_boost": None,
    "supports_cycle": False,
}

ASUS_DATA: dict[str, DeviceTDP] = {
    "ROG Ally RC71L": ALLY_DATA,
    "ROG Ally X RC72L": ALLYX_DATA,
    "ROG Flow Z13 GZ302": Z1_DATA,
}

CLAW_DATA: DeviceTDPv2 = {
    "quiet": (20, 20, None),
    "balanced_min": 21,
    "balanced": (30, 30, None),
    "performance_min": 36,
    "performance_dc": 35,
    "performance": (35, 35, None),
    "min_tdp": 20,
    "max_tdp_dc": 35,
    "max_tdp": 43,
    "max_tdp_oc": 45,
    "max_tdp_sppt": 45,
    "max_tdp_fppt": None,
    "supports_cycle": True,
}

CLAW_AI_DATA: DeviceTDPv2 = {
    "quiet": (8, 37, None),
    "balanced_min": 9,
    "balanced": (12, 37, None),
    "performance_min": 16,
    "performance_dc": 30,
    "performance": (30, 37, None),
    "min_tdp": 8,
    "max_tdp_dc": 30,
    "max_tdp": 30,
    "max_tdp_oc": 30,
    "max_tdp_sppt": 37,
    "max_tdp_fppt": None,
    "supports_cycle": True,
}

CLAW_8A_DATA: DeviceTDPv2 = {
    "quiet": (15, 28, 33),
    "balanced_min": 17,
    "balanced": (20, 33, 43),
    "performance_min": 23,
    "performance_dc": 28,
    "performance": (28, 45, 55),
    "min_tdp": 8,
    "max_tdp_dc": 35,
    "max_tdp": 35,
    "max_tdp_oc": 35,
    "max_tdp_sppt": 37,
    "max_tdp_fppt": 55,
    "supports_cycle": True,
}

MSI_DATA: dict[str, DeviceTDPv2] = {
    "MS-1T41": CLAW_DATA,
    "MS-1T42": CLAW_AI_DATA,
    "MS-1T52": CLAW_AI_DATA,
    "MS-1T8K": CLAW_8A_DATA,
}
