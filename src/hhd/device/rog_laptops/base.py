
import logging
import time
import select
from threading import Event as TEvent
from typing import Sequence, Literal

from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.plugins import Config, Context, Emitter
from hhd.controller import Event

from .const import GA403_PID_ALT
from .fan import FanControl
from .slash import SlashControl

logger = logging.getLogger(__name__)

ASUS_VID = 0x0B05

REPORT_DELAY_MAX = 0.5 

class RogLaptopHidraw(GenericGamepadHidraw):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.slash: SlashControl | None = None
        self.fans = FanControl()

    def open(self) -> Sequence[int]:
        self.fds = super().open()
        if self.dev:
            alt_mode = False
            if self.info and self.info.get('product_id') == GA403_PID_ALT:
                alt_mode = True
                logger.debug(f"Using ALT mode (193B) for Slash Lighting")
            else:
                logger.debug(f"Using standard mode for Slash Lighting (PID: {self.info.get('product_id') if self.info else 'unknown'})")
                
            self.slash = SlashControl(self.dev, alt_mode=alt_mode)
            self.slash.init()
        return self.fds
    
    def update_conf(self, conf: Config):
        if self.slash:
            try:
                self.slash.update(
                    conf["slash_lighting"].to(bool),
                    conf["slash_pattern"]["mode"].to(str),
                    conf["slash_speed"].to(str),
                    conf["slash_brightness"].to(str),
                )
            except Exception as e:
                logger.warning(f"Error updating slash lighting: {e}")
        
        try:
            mode = conf["fan_mode"].to(str)
            if mode == "Auto":
                self.fans.set_auto()
            elif mode == "Quiet":
                self.fans.set_quiet()
            elif mode == "Performance":
                self.fans.set_performance()
            elif mode == "Max":
                self.fans.set_max()
        except Exception as e:
            logger.warning(f"Error setting fan mode: {e}")
 

def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    target_device: str,
    report_id: int,
):
    # Only support GA403 for now regarding PID
    # Only use 193B (ALT) for Slash Lighting!
    # 19B6 is a different interface that doesn't support Slash via Feature Reports.
    # enumerate_unique sorts by path, so 19B6 (/dev/hidraw0) would be picked first.
    pids = [GA403_PID_ALT]  # 0x193B only
    if target_device != "GA403":
        logger.warning(f"Unknown device {target_device}, defaulting to PIDs {pids}")
    
    logger.info(f"RogLaptop: Loaded with PIDs: {pids} and strictly no usage page check.")

    while not should_exit.is_set():
        try:
            logger.info(f"Starting Asus Laptop support for {target_device}...")
            
            d_hid = RogLaptopHidraw(
                vid=[ASUS_VID],
                pid=pids,
                required=True,
                report_size=64,
            )
            
            d_hid.open()
            
            d_hid.update_conf(conf)
            
            loop_count = 0
            while not should_exit.is_set():
                loop_count += 1
                if updated.is_set():
                    updated.clear()
                    d_hid.update_conf(conf)
                
                # Slow loop as we are not polling high freq inputs from this device
                start = time.time()
                # Just wait, don't read - we're not processing input from this device
                time.sleep(REPORT_DELAY_MAX)

        except Exception as e:
            logger.error(f"Error in RogLaptop plugin: {e}")
            time.sleep(3)
        finally:
            try:
                d_hid.close()
            except:
                pass

