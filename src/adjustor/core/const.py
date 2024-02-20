from .alib import A, D, DeviceParams, AlibParams

ALIB_PARAMS = {
    # TDPs
    "stapm_limit": A(0x05, 0, 54, 1000),
    "fast_limit": A(0x06, 0, 54, 1000),
    "slow_limit": A(0x07, 0, 54, 1000),
    "skin_limit": A(0x2E, 0, 100, 1000),
    # Times
    "slow_time": A(0x08, 0, 30),
    "stapm_time": A(0x01, 0, 300),
    # Temp
    "temp_target": A(0x03, 0, 105),
}

ALIB_PARAMS_REMBRANDT: dict[str, AlibParams] = ALIB_PARAMS

DEV_PARAMS_REMBRANDT: dict[str, DeviceParams] = {
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

DEV_PARAMS_LEGO = DEV_PARAMS_REMBRANDT

CPU_DATA = {"AMD Ryzen Z1 Extreme": (DEV_PARAMS_REMBRANDT, ALIB_PARAMS_REMBRANDT)}
