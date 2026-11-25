import unittest
from unittest.mock import patch

from hhd.device.zotac import hid
from hhd.device.zotac.hid import (
    CMD_GET_MAPPING,
    CMD_SET_MAPPING,
    CMD_SET_RGB,
    CMD_SET_VIBRATION,
    EFFECT_DELAY,
    SRC_M1,
    SRC_M2,
    ZotacCmdHidraw,
    ZotacDialHidraw,
    action_target,
    rgb_cmds,
    zotac_cmd,
    zotac_crc,
)

# Reply of the controller (firmware 1.3.9.1) to 0xA2 (get mapping) for M1
# while M1 was mapped to F22, including the CRC computed by the firmware.
REPLY_GET_M1 = bytes.fromhex(
    "e100423ca2010000000000007100000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000b02a"
)

NO_ZONES: dict[int, str] = {}


def led_event(mode: str, zotac=None, red=1):
    return {
        "type": "led",
        "initialize": True,
        "code": "main",
        "mode": mode,
        "direction": "left",
        "brightness": 0.5,
        "brightnessd": "high",
        "speed": 1,
        "speedd": "high",
        "red": red,
        "green": 2,
        "blue": 3,
        "red2": red,
        "green2": 2,
        "blue2": 3,
        "oxp": None,
        "zotac": zotac,
    }


class FakeCmdDevice:
    """Answers commands like the controller: replies echo the command."""

    def __init__(self):
        self.writes: list[bytes] = []
        self.replies: list[bytes] = []

    def write(self, data: bytes):
        self.writes.append(bytes(data))
        rep = bytearray(64)
        rep[0:5] = data[1:6]
        self.replies.append(bytes(rep))
        return len(data)

    def read(self, size: int, timeout=None):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        pass


class FakeDial:
    def __init__(self, reports: list[bytes]):
        self.reports = reports

    def read(self, size):
        return self.reports.pop(0)


def open_cmd_device(fake: FakeCmdDevice, **kwargs) -> ZotacCmdHidraw:
    device = ZotacCmdHidraw(**{"vibration": 100, "touchpad_zones": NO_ZONES, **kwargs})

    def fake_open(self):
        self.dev = fake
        self.fd = 42
        return [42]

    with patch.object(hid.GenericGamepadHidraw, "open", fake_open):
        device.open()
    return device


class ZotacProtocolTest(unittest.TestCase):
    def test_crc_matches_controller_reply(self):
        self.assertEqual(
            zotac_crc(REPLY_GET_M1[4:62]).to_bytes(2, "big"), REPLY_GET_M1[62:64]
        )

    def test_command_layout(self):
        pkt = zotac_cmd(CMD_GET_MAPPING, bytes([SRC_M1]), 0x42)
        self.assertEqual(len(pkt), 65)
        self.assertEqual(pkt[0], 0)  # report id
        # Same header and sequence as the controller echoes in its reply
        self.assertEqual(pkt[1:6], REPLY_GET_M1[0:5])
        self.assertEqual(pkt[5:7], bytes([CMD_GET_MAPPING, SRC_M1]))
        self.assertEqual(pkt[63:65], zotac_crc(pkt[5:63]).to_bytes(2, "big"))


class ZotacRgbTest(unittest.TestCase):
    def test_modes_map_to_effects(self):
        expected = {
            ("solid", None): 0x04,
            ("pulse", None): 0x01,
            ("strobe", None): 0x06,
            ("rainbow", None): 0x03,
            ("spiral", None): 0x00,
            ("zotac", "stars"): 0x02,
            ("zotac", "random"): 0x07,
            ("zotac", "flash"): 0x05,
        }
        for (mode, style), effect in expected.items():
            with self.subTest(mode=mode, style=style):
                cmds = rgb_cmds(led_event(mode, style))
                # Off first, so an effect restored from flash restarts
                self.assertEqual(cmds[0], (bytes([0x02, 0xF0]), EFFECT_DELAY))
                self.assertEqual(cmds[1], (bytes([0x02, effect]), EFFECT_DELAY))
                # Color for both LED sets, then speed and brightness
                color = bytes([1, 2, 3]) * 10
                self.assertEqual(cmds[2][0], bytes([0x00, 0, 0, 0]) + color)
                self.assertEqual(cmds[3][0], bytes([0x00, 1, 0, 0]) + color)
                self.assertEqual(cmds[4][0], bytes([0x01, 2]))
                self.assertEqual(cmds[5][0], bytes([0x03, 50]))

    def test_disabled_turns_leds_off(self):
        self.assertEqual(
            rgb_cmds(led_event("disabled")), [(bytes([0x02, 0xF0]), EFFECT_DELAY)]
        )

    def send_all(self, device: ZotacCmdHidraw, fake: FakeCmdDevice, ev) -> list[bytes]:
        fake.writes.clear()
        device.consume([ev])
        while device.queue:
            device.next_write = 0
            device.consume([])
        return [w[6:8] for w in fake.writes if w[5] == CMD_SET_RGB]

    def test_color_change_keeps_running_effect(self):
        fake = FakeCmdDevice()
        device = open_cmd_device(fake)

        sent = self.send_all(device, fake, led_event("pulse"))
        self.assertEqual(sent[:2], [bytes([0x02, 0xF0]), bytes([0x02, 0x01])])

        # Same effect, new color: no effect change, the band does not blank
        sent = self.send_all(device, fake, led_event("pulse", red=9))
        self.assertNotIn(0x02, [s[0] for s in sent])
        self.assertEqual(len(sent), 4)

        # New effect: through off again
        sent = self.send_all(device, fake, led_event("solid"))
        self.assertEqual(sent[:2], [bytes([0x02, 0xF0]), bytes([0x02, 0x04])])

    def test_new_state_replaces_pending_commands(self):
        fake = FakeCmdDevice()
        device = open_cmd_device(fake)
        device.next_write = float("inf")
        device.consume([led_event("pulse")])
        device.consume([led_event("solid")])
        self.assertEqual(device.queue[1][0], bytes([0x02, 0x04]))

    def test_reconnect_sets_effect_again(self):
        fake = FakeCmdDevice()
        device = open_cmd_device(fake)
        self.send_all(device, fake, led_event("pulse"))

        # After a reconnect the controller runs its stored effect again
        device = open_cmd_device(fake)
        sent = self.send_all(device, fake, led_event("pulse", red=9))
        self.assertEqual(sent[:2], [bytes([0x02, 0xF0]), bytes([0x02, 0x01])])


class ZotacCmdTest(unittest.TestCase):
    def test_paddles_and_vibration(self):
        fake = FakeCmdDevice()
        device = open_cmd_device(fake, vibration=75)

        cmds = [(w[5], w[6:20]) for w in fake.writes]
        self.assertEqual(
            cmds,
            [
                (CMD_SET_MAPPING, bytes([SRC_M1]) + action_target("f22")),
                (CMD_SET_MAPPING, bytes([SRC_M2]) + action_target("f21")),
                (CMD_SET_VIBRATION, bytes([75, 75]) + bytes(12)),
            ],
        )

        # Mappings are volatile and not restored on close
        fake.writes.clear()
        device.close(True)
        self.assertEqual(fake.writes, [])

    def test_touchpad_zones(self):
        zones = {
            0x03: "touchpad_click",
            0x04: "touchpad_right",
            0x05: "dpad_left",
            0x06: "y",
            0x07: "rs",
            0x08: "disabled",
            0x09: "mouse_left",
            0x0A: "mouse_right",
        }
        fake = FakeCmdDevice()
        open_cmd_device(fake, touchpad_zones=zones)
        targets = {w[6]: w[7:20] for w in fake.writes if w[5] == CMD_SET_MAPPING}

        def target(**set_bytes):
            t = bytearray(13)
            for idx, val in set_bytes.items():
                t[int(idx[1:])] = val
            return bytes(t)

        self.assertEqual(targets[SRC_M1], target(b6=hid.HID_KEY_F22))
        self.assertEqual(targets[SRC_M2], target(b6=hid.HID_KEY_F21))
        self.assertEqual(targets[0x03], target(b6=hid.HID_KEY_F13))
        self.assertEqual(targets[0x04], target(b6=hid.HID_KEY_F14))
        self.assertEqual(targets[0x05], target(b0=0x04))
        self.assertEqual(targets[0x06], target(b1=0x80))
        self.assertEqual(targets[0x07], target(b0=0x80))
        self.assertEqual(targets[0x08], bytes(13))
        self.assertEqual(targets[0x09], target(b12=0x01))
        self.assertEqual(targets[0x0A], target(b12=0x02))


class ZotacDialTest(unittest.TestCase):
    def test_detent_is_a_short_press(self):
        device = ZotacDialHidraw(left="brightness", right="volume")
        device.fd = 42
        device.dev = FakeDial(  # type: ignore
            [
                bytes([0x03, 0, 0, 0x01]) + bytes(60),  # right dial clockwise
                bytes([0x03]) + bytes(63),  # null report after each detent
                bytes([0x03, 0, 0, 0x10]) + bytes(60),  # left dial counterclockwise
            ]
        )
        with patch.object(hid, "can_read", side_effect=[True] * 3 + [False]):
            self.assertEqual(
                device.produce([42]),
                [
                    {"type": "button", "code": "key_volumeup", "value": True},
                    {"type": "button", "code": "key_brightnessdown", "value": True},
                ],
            )
        # Released on the next iteration
        self.assertEqual(
            device.produce([]),
            [
                {"type": "button", "code": "key_volumeup", "value": False},
                {"type": "button", "code": "key_brightnessdown", "value": False},
            ],
        )

    def test_disabled_dial_is_ignored(self):
        device = ZotacDialHidraw(left="disabled", right="volume")
        device.fd = 42
        device.dev = FakeDial([bytes([0x03, 0, 0, 0x08]) + bytes(60)])  # type: ignore
        with patch.object(hid, "can_read", side_effect=[True, False]):
            self.assertEqual(device.produce([42]), [])


if __name__ == "__main__":
    unittest.main()
