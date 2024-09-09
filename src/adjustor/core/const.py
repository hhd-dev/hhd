from .alib import A, D, DeviceParams, AlibParams

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

DEV_PARAMS_5000: dict[str, DeviceParams] = DEV_PARAMS_25W
DEV_PARAMS_6000: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_7040: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_8040: dict[str, DeviceParams] = DEV_PARAMS_30W
DEV_PARAMS_LEGO = DEV_PARAMS_30W

DEV_DATA: dict[str, tuple[dict[str, DeviceParams], dict[str, AlibParams], bool]] = {
    "NEO-01": (DEV_PARAMS_28W, ALIB_PARAMS_7040, False),
    "V3": (DEV_PARAMS_28W, ALIB_PARAMS_8040, False),
    "83E1": (DEV_PARAMS_LEGO, ALIB_PARAMS_7040, False),
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
}
