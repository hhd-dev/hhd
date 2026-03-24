
import logging
import os
from typing import Sequence

logger = logging.getLogger(__name__)

class FanControl:
    def __init__(self):
        self.path = None
        self.current_mode = None
        self.find_device()

    def find_device(self):
        try:
            base = "/sys/class/hwmon"
            for dev in os.listdir(base):
                path = os.path.join(base, dev)
                name_path = os.path.join(path, "name")
                if not os.path.exists(name_path):
                    continue
                if not os.path.exists(name_path):
                    continue
                with open(name_path, "r") as f:
                    name = f.read().strip()
                logger.debug(f"Found hwmon device: {name} at {path}")
                if name == "asus_custom_fan_curve":
                    self.path = path
                    logger.info(f"Found Asus fan control at {self.path}")
                    return
        except Exception as e:
            logger.error(f"Error finding fan device: {e}")
        
        logger.warning("Asus fan control device not found.")

    def set_curve(self, fan_idx: int, curve: Sequence[tuple[int, int]], enable: bool = True):
        # fan_idx: 1=CPU, 2=GPU, 3=Mid
        if not self.path:
            return
        
        try:
            # Write points
            for i, (temp, pwm) in enumerate(curve):
                if i >= 8: break
                
                # pwmX_auto_pointY_temp / pwm
                # points are 1-indexed in sysfs, 0-indexed in list
                pt = i + 1
                
                t_path = os.path.join(self.path, f"pwm{fan_idx}_auto_point{pt}_temp")
                p_path = os.path.join(self.path, f"pwm{fan_idx}_auto_point{pt}_pwm")

                with open(t_path, "w") as f:
                    f.write(str(temp))
                with open(p_path, "w") as f:
                    f.write(str(pwm))

            # Enable/Disable
            # 1 = Manual/Custom Curve (Enabled)
            # 2 = Auto/Default (Disabled)
            mode = "1" if enable else "2"
            e_path = os.path.join(self.path, f"pwm{fan_idx}_enable")
            with open(e_path, "w") as f:
                f.write(mode)
                
        except Exception as e:
            logger.error(f"Failed to set fan curve for fan {fan_idx}: {e}")

    def set_auto(self):
        if self.current_mode == "Auto":
            return
        if not self.path:
            return
        
        # Enable = 2 (Auto) for all fans (CPU=1, GPU=2, Mid=3)
        for i in range(1, 4):
            try:
                e_path = os.path.join(self.path, f"pwm{i}_enable")
                if os.path.exists(e_path):
                     with open(e_path, "w") as f:
                        f.write("2")
            except Exception as e:
                # Some might not exist (e.g. Mid)
                pass
        self.current_mode = "Auto"
        # logger.info("Set fans to Auto mode.")
        logger.debug("Set fans to Auto mode.")

    def set_max(self):
        if self.current_mode == "Max":
            return
        if not self.path:
            logger.warning("set_max: No fan control path found")
            return
            
        # asus_custom_fan_curve uses pwmX_auto_pointY_pwm for fan curves
        # Set enable=1 (custom curve) and all curve points to max
        for i in range(1, 4):  # pwm1, pwm2, pwm3
            try:
                # Enable custom fan curve
                e_path = os.path.join(self.path, f"pwm{i}_enable")
                if os.path.exists(e_path):
                    with open(e_path, "w") as f:
                        f.write("1")
                
                # Set all 8 curve points to maximum (255)
                for point in range(1, 9):  # points 1-8
                    p_path = os.path.join(self.path, f"pwm{i}_auto_point{point}_pwm")
                    if os.path.exists(p_path):
                        with open(p_path, "w") as f:
                            f.write("255")
            except Exception as e:
                logger.warning(f"set_max: Error setting pwm{i}: {e}")
        self.current_mode = "Max"
        logger.debug("Set fans to Max mode.")

    def set_quiet(self):
        """Set fans to quiet mode - lower speeds to reduce noise."""
        if self.current_mode == "Quiet":
            return
        if not self.path:
            logger.warning("set_quiet: No fan control path found")
            return
        
        # Quiet curve: gradual ramp, lower max values
        # Points are (temp, pwm) pairs - we set PWM values
        quiet_curve = [30, 40, 50, 60, 80, 100, 120, 140]  # Max 140 out of 255
        
        for i in range(1, 4):  # pwm1, pwm2, pwm3
            try:
                e_path = os.path.join(self.path, f"pwm{i}_enable")
                if os.path.exists(e_path):
                    with open(e_path, "w") as f:
                        f.write("1")
                
                for point, pwm in enumerate(quiet_curve, 1):
                    p_path = os.path.join(self.path, f"pwm{i}_auto_point{point}_pwm")
                    if os.path.exists(p_path):
                        with open(p_path, "w") as f:
                            f.write(str(pwm))
            except Exception as e:
                logger.warning(f"set_quiet: Error setting pwm{i}: {e}")
        self.current_mode = "Quiet"
        logger.debug("Set fans to Quiet mode.")

    def set_performance(self):
        """Set fans to performance mode - higher speeds for better cooling."""
        if self.current_mode == "Performance":
            return
        if not self.path:
            logger.warning("set_performance: No fan control path found")
            return
        
        # Performance curve: aggressive ramp, higher PWM values
        perf_curve = [60, 80, 120, 160, 200, 230, 250, 255]  # Max out at 255
        
        for i in range(1, 4):  # pwm1, pwm2, pwm3
            try:
                e_path = os.path.join(self.path, f"pwm{i}_enable")
                if os.path.exists(e_path):
                    with open(e_path, "w") as f:
                        f.write("1")
                
                for point, pwm in enumerate(perf_curve, 1):
                    p_path = os.path.join(self.path, f"pwm{i}_auto_point{point}_pwm")
                    if os.path.exists(p_path):
                        with open(p_path, "w") as f:
                            f.write(str(pwm))
            except Exception as e:
                logger.warning(f"set_performance: Error setting pwm{i}: {e}")
        self.current_mode = "Performance"
        logger.debug("Set fans to Performance mode.")

