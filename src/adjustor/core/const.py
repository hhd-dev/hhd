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


PLATFORM_PROFILE_MAP = [
    ("low-power", 0),
    ("quiet", 0),
    ("balanced", 13),
    ("performance", 20),
]
ENERGY_MAP = [
    ("power", 0),
    ("balanced", 13),
    ("performance", 20),
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

DEV_PARAMS_28W: dict[str, DeviceParams] = {
    "stapm_limit": D(0, 4, 15, 28, 35),
    "skin_limit": D(0, 4, 15, 28, 35),
    "slow_limit": D(0, 4, 20, 32, 37),
    "fast_limit": D(0, 4, 25, 35, 40),
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

DEV_DATA: dict[str, tuple[dict[str, DeviceParams], dict[str, AlibParams], bool]] = {
    "NEO-01": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
    "V3": (DEV_PARAMS_28W, ALIB_PARAMS_8040, False),
    "83E1": (DEV_PARAMS_LEGO, ALIB_PARAMS_7040, False),
    "ONEXPLAYER F1Pro": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, False),
    "ONEXPLAYER F1 EVA-02": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370, False),
    # GPD Devices are 28W max
    "G1618-04": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
    "G1617-01": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
    "G1619-04": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
    "G1619-05": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
}

CPU_DATA: dict[str, tuple[dict[str, DeviceParams], dict[str, AlibParams]]] = {
    "AMD Ryzen Z1 Extreme": (DEV_PARAMS_7040, ALIB_PARAMS_7040),
    "AMD Ryzen Z1": (DEV_PARAMS_7040, ALIB_PARAMS_7040),
    # GPD Win 4
    # model name    : AMD Ryzen 7 6800U with Radeon Graphics
    # 28W works fine, 30W is pushing it
    "AMD Ryzen 7 5800U": (DEV_PARAMS_6000, ALIB_PARAMS_6040),
    "AMD Ryzen 7 6800U": (DEV_PARAMS_6000, ALIB_PARAMS_6040),
    "AMD Ryzen 7 7840U": (DEV_PARAMS_7040, ALIB_PARAMS_7040),
    "AMD Ryzen 7 8840U": (DEV_PARAMS_8040, ALIB_PARAMS_8040),
    # AMD Athlon Silver 3050e (Win600, will it support tdp?)
    "AMD Ryzen AI 9 HX 370": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370),
    "AMD Ryzen AI HX 360": (DEV_PARAMS_HX370, ALIB_PARAMS_HX370),
}
