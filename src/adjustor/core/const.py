from .alib import A, D, DeviceParams, AlibParams

ROG_ALLY_PP_MAP = [
    ("low-power", 0),
    ("quiet", 0),
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

ALIB_PARAMS_7040: dict[str, AlibParams] = ALIB_PARAMS

DEV_PARAMS_7040: dict[str, DeviceParams] = {
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

ALIB_PARAMS_6040: dict[str, AlibParams] = ALIB_PARAMS
DEV_PARAMS_6040: dict[str, DeviceParams] = DEV_PARAMS_7040

DEV_PARAMS_LEGO = DEV_PARAMS_7040

DEV_DATA: dict[str, tuple[dict[str, DeviceParams], dict[str, AlibParams], bool]] = {
    "NEO-01": (DEV_PARAMS_7040, ALIB_PARAMS_7040, False),
    "83E1": (DEV_PARAMS_LEGO, ALIB_PARAMS_7040, False),
}

CPU_DATA: dict[str, tuple[dict[str, DeviceParams], dict[str, AlibParams]]] = {
    "AMD Ryzen Z1 Extreme": (DEV_PARAMS_7040, ALIB_PARAMS_7040),
    "AMD Ryzen 7 7840U": (DEV_PARAMS_7040, ALIB_PARAMS_7040),
    # GPD Win 4
    # model name    : AMD Ryzen 7 6800U with Radeon Graphics
    # 28W works fine, 30W is pushing it
    "AMD Ryzen 7 6800U": (DEV_PARAMS_6040, ALIB_PARAMS_6040),
}
