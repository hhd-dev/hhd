from enum import Enum
import logging
import glob
import re
import time
import subprocess

logger = logging.getLogger(__name__)

class GpuMode(Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"

GPU_FREQUENCY_PATH = glob.glob("/sys/class/drm/card?/device/pp_od_clk_voltage")[0]
GPU_LEVEL_PATH = glob.glob("/sys/class/drm/card?/device/power_dpm_force_performance_level")[0]

def get_gpu_frequency_range():
    try:
        freq_string = open(GPU_FREQUENCY_PATH,"r").read()
        od_sclk_matches = re.findall(r"OD_RANGE:\s*SCLK:\s*(\d+)Mhz\s*(\d+)Mhz", freq_string)

        if od_sclk_matches:
            frequency_range = [int(od_sclk_matches[0][0]), int(od_sclk_matches[0][1])]
            return frequency_range
    except Exception as e:
        logger.error(f"Error while retrieving GPU frequency range {e}")

def set_gpu_frequency(gpu_mode: GpuMode, gpu_range: list[int] = []):
    if gpu_mode == GpuMode.AUTO:
        try:
            with open(GPU_LEVEL_PATH,'w') as f:
                f.write("auto")
                f.close()
            return True
        except Exception as e:
            logger.error(f"GPU auto mode error {e}")
            return False
    elif gpu_mode == GpuMode.MANUAL and len(gpu_range) == 2:
        min, max = gpu_range

        return set_gpu_frequency_range(min, max)
    else:
        return False

def set_gpu_frequency_range(new_min: int, new_max: int):
    try:
        min, max = get_gpu_frequency_range()

        if not (new_min >= min and new_max <= max and new_min <= new_max):
            # invalid min/max values, return False
            logger.info(f"Invalid GPU frequency range {new_min}, {new_max}")
            return False

        with open(GPU_LEVEL_PATH,'w') as file:
            file.write("manual")
            file.close()

        time.sleep(0.1)

        logger.info(f"Setting GPU range to {new_min} {new_max}")

        execute_gpu_frequency_command(f"s 0 {new_min}")
        execute_gpu_frequency_command(f"s 1 {new_max}")
        execute_gpu_frequency_command("c")

        return True
    except Exception as e:
        logger.error(f"set_gpu_frequency_range {new_min} {new_max} error {e}")
        return False
  

def execute_gpu_frequency_command(command):
    cmd = f"echo '{command}' | tee {GPU_FREQUENCY_PATH}"
    subprocess.run(cmd, shell=True, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
