import unittest
from unittest.mock import Mock, patch
from threading import Event

from hhd.device.claw import ClawControllerPlugin
from hhd.device.claw.base import (
    ClawDInputHidraw,
    CLAW_CALIB,
    CLAW_SYNC_ROM,
    CLAW_CAL_LT,
    CLAW_CAL_RT,
    CLAW_CAL_LS,
    CLAW_CAL_RS,
)
from hhd.plugins import Config


def fe_ack(in_cal, mask):
    return bytes([0x10, 0x00, 0x00, 0x3C, 0xFE, 1 if in_cal else 0, mask]) + bytes(57)


def short(cmd):
    # Commands are 64-byte padded; compare the meaningful prefix.
    return cmd[:6].ljust(6, b"\x00")


class CalibTest(unittest.TestCase):
    def make(self):
        d = ClawDInputHidraw()
        d.dev = Mock()
        return d

    def writes(self, d):
        return [c.args[0][:6] for c in d.dev.write.call_args_list if c.args]

    def test_full_flow(self):
        d = self.make()
        acks = [
            fe_ack(True, 0),
            fe_ack(True, CLAW_CAL_LS),
            fe_ack(True, CLAW_CAL_LT | CLAW_CAL_RT | CLAW_CAL_LS | CLAW_CAL_RS),
        ]
        d.dev.read.side_effect = lambda size, timeout=None: (
            acks.pop(0) if acks else b""
        )
        ok = d.calibrate()
        self.assertTrue(ok)
        writes = self.writes(d)
        self.assertIn(short(CLAW_CALIB + b"\x00"), writes)  # enter
        self.assertIn(short(CLAW_CALIB + b"\x01"), writes)  # complete
        self.assertIn(short(CLAW_SYNC_ROM), writes)  # persist
        self.assertNotIn(short(CLAW_CALIB + b"\x02"), writes)  # no cancel

    def test_cancel_on_missing_components(self):
        d = self.make()
        d.dev.read.return_value = fe_ack(True, CLAW_CAL_LS)
        ok = d.calibrate(timeout=0.5)
        self.assertFalse(ok)
        writes = self.writes(d)
        self.assertIn(short(CLAW_CALIB + b"\x02"), writes)  # cancelled
        self.assertNotIn(short(CLAW_CALIB + b"\x01"), writes)  # never completed

    def test_abort_callback(self):
        d = self.make()
        stop = Event()
        stop.set()
        d.dev.read.return_value = b""
        ok = d.calibrate(should_abort=stop.is_set)
        self.assertFalse(ok)
        self.assertIn(short(CLAW_CALIB + b"\x02"), self.writes(d))

    def test_mcu_left_cal_mode(self):
        d = self.make()
        d.dev.read.return_value = fe_ack(False, 0)
        ok = d.calibrate()
        self.assertFalse(ok)
        self.assertNotIn(short(CLAW_CALIB + b"\x01"), self.writes(d))

    def test_plugin_update_triggers_recalibrate_action(self):
        plugin = ClawControllerPlugin("MS-1T52", {"name": "Claw 8"})
        plugin.prev = None
        conf = Config(
            {
                "controllers": {
                    "claw": {
                        "dinput_mode": False,
                        "recalibrate_sticks": False,
                    }
                }
            }
        )
        with patch.object(plugin, "start"):
            plugin.update(conf)
            plugin.updated.clear()

            # Triggering only the action (no other config changes) must still
            # wake the controller loop and reset the action key in conf.
            conf["controllers.claw.recalibrate_sticks"] = True
            plugin.update(conf)

            self.assertFalse(conf["controllers.claw.recalibrate_sticks"].to(bool))
            self.assertTrue(plugin.updated.is_set())
            self.assertTrue(plugin.prev.get_action("recalibrate_sticks"))
            self.assertFalse(plugin.prev.get_action("recalibrate_sticks"))


if __name__ == "__main__":
    unittest.main()
