
import logging
from typing import Literal

from .const import (
    SLASH_DISABLE,
    SLASH_ENABLE,
    SLASH_INIT_1,
    SLASH_INIT_2,
    SLASH_DISABLE_ALT,
    SLASH_ENABLE_ALT,
    SLASH_INIT_1_ALT,
    SLASH_INIT_2_ALT,
    SLASH_APPLY,
    SLASH_APPLY_ALT,
    SLASH_MODES,
    SLASH_SPEEDS,
    SLASH_BRIGHTNESS,
    buf,
)

logger = logging.getLogger(__name__)

class SlashControl:
    def __init__(self, dev, alt_mode: bool = False):
        self.dev = dev
        self.alt_mode = alt_mode
        self.enabled = None
        self.pattern = None
        self.speed = None
        self.brightness = None

    def init(self):
        if not self.dev:
            return
        try:
            if self.alt_mode:
                # Use Feature Reports for 193B (Control Transfer 0x35E)
                self.dev.send_feature_report(SLASH_INIT_1_ALT)
                self.dev.send_feature_report(SLASH_INIT_2_ALT)
                
                # Default init options
                self.update(True, "Flow", "Normal", "Medium", force=True)
            else:
                self.dev.write(SLASH_INIT_1)
                self.dev.write(SLASH_INIT_2)
            logger.debug("Initialized Slash Lighting.")
        except Exception as e:
            logger.error(f"Failed to initialize Slash Lighting: {e}")

    def _get_mode_packets(self, mode: str):
        mode_byte = SLASH_MODES.get(mode, 0x19) # Default Flow
        rid = 0x5E if self.alt_mode else 0x5D
        pkt1 = buf([rid, 0xD2, 0x03, 0x00, 0x0C])
        pkt2 = buf([rid, 0xD3, 0x04, 0x00, 0x0C, 0x01, mode_byte, 0x02, 0x19, 0x03, 0x13, 0x04, 0x11, 0x05, 0x12, 0x06, 0x13])
        return pkt1, pkt2

    def _get_options_packet(self, enable: bool, speed: str, brightness: str):
        rid = 0x5E if self.alt_mode else 0x5D
        status = 0x01 if enable else 0x00
        interval = SLASH_SPEEDS.get(speed, 0x03)
        bright_val = SLASH_BRIGHTNESS.get(brightness, 120)
        
        return buf([rid, 0xD3, 0x03, 0x01, 0x08, 0xAB, 0xFF, 0x01, status, 0x06, bright_val, 0xFF, interval])

    def update(self, enable: bool, pattern: str, speed: str, brightness: str, force: bool = False):
        if not self.dev:
            return

        if not force and (
            self.enabled == enable and
            self.pattern == pattern and
            self.speed == speed and
            self.brightness == brightness
        ):
            return

        try:
            # 1. Update Pattern if changed
            if force or self.pattern != pattern:
                p1, p2 = self._get_mode_packets(pattern)
                logger.debug(f"Setting Slash Pattern to {pattern}")
                if self.alt_mode:
                    self.dev.send_feature_report(p1)
                    self.dev.send_feature_report(p2)
                else:
                    self.dev.write(p1)
                    self.dev.write(p2)

            # 2. Update Options (Brightness/Speed) or Enable Status if changed
            # The options packet contains Status, Brightness AND Interval.
            # So we should send it if ANY of enable, speed, brightness changed.
            if force or self.enabled != enable or self.speed != speed or self.brightness != brightness:
                opt_pkt = self._get_options_packet(enable, speed, brightness)
                logger.debug(f"Setting Slash Options: En={enable}, Spd={speed}, Brt={brightness}")
                if self.alt_mode:
                    self.dev.send_feature_report(opt_pkt)
                else:
                    self.dev.write(opt_pkt)

            # 3. Enable/Disable packet (Command 0xD8)
            if force or self.enabled != enable:
                if enable:
                    if self.alt_mode:
                         self.dev.send_feature_report(SLASH_ENABLE_ALT)
                    else:
                         self.dev.write(SLASH_ENABLE)
                else:
                    if self.alt_mode:
                         self.dev.send_feature_report(SLASH_DISABLE_ALT)
                    else:
                         self.dev.write(SLASH_DISABLE)

            # 4. Apply
            if self.alt_mode:
                self.dev.send_feature_report(SLASH_APPLY_ALT)
            else:
                self.dev.write(SLASH_APPLY)

            # Update state
            self.enabled = enable
            self.pattern = pattern
            self.speed = speed
            self.brightness = brightness

        except Exception as e:
            logger.error(f"Failed to update Slash Lighting: {e}")

    # Compatibility method for old calls
    def set_status(self, enable: bool):
        # Default to current or default values if not set
        p = self.pattern or "Flow"
        s = self.speed or "Normal"
        b = self.brightness or "Medium"
        self.update(enable, p, s, b)
