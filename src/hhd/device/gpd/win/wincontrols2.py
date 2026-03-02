import logging
import time

from hhd.controller.lib.hid import Device, enumerate_unique
from hhd.device.gpd.win.wincontrols import (
    ACTION_MAP,
    PAUSE,
    RUMBLE_MODES,
)

logger = logging.getLogger(__name__)

VID = 0x2F24
PID = 0x0137
PKTSIZE = 64
DATA_PER_PKT = 56  # bytes 8-63 of each packet
HEADER_SIZE = 12  # transfer header echoed back on writes

# --- V2 Keyboard mode button offsets (config bytes 0-41) ---
# Each entry is 2 bytes (uint16_t LE)
KB_BUTTON_MAP = {
    "dpad_up": 0,
    "dpad_down": 2,
    "dpad_left": 4,
    "dpad_right": 6,
    "start": 8,
    "select": 10,
    "menu": 12,
    "a": 14,
    "b": 16,
    "x": 18,
    "y": 20,
    "lb": 22,
    "rb": 24,
    "lt": 26,
    "rt": 28,
    "ls": 30,
    "rs": 32,
    "ls_up": 34,
    "ls_down": 36,
    "ls_left": 38,
    "ls_right": 40,
}

# --- V2 Settings offsets (config bytes 944-959) ---
SETTING_RUMBLE = 944
SETTING_RGB_CONTROL = 945
SETTING_RGB_RED = 946
SETTING_RGB_GREEN = 947
SETTING_RGB_BLUE = 948

DEADZONE_MAP = {
    "ls_center": 949,
    "ls_boundary": 950,
    "rs_center": 951,
    "rs_boundary": 952,
}

# V2 RGB encoding (bit7=on/off, bits 0-6=mode)
# Names match V1 for ABI compatibility
RGB_MODES = {
    "off": 0x00,
    "constant": 0x80,  # solid
    "breathed": 0x81,  # breathing
    "rotated": 0x82,  # gradient
}

# --- V2 Back button regions (config bytes 160-943) ---
BB_OFFSETS = {"bb1": 160, "bb2": 356, "bb3": 552, "bb4": 748}
BB_REGION_SIZE = 196

# V1-style extra buttons -> (back_button_name, slot_index)
# BB1 = left back button macro chain (extra_l1..l4)
# BB2 = right back button macro chain (extra_r1..r4)
EXTRA_TO_BB = {
    "extra_l1": ("bb1", 0),
    "extra_l2": ("bb1", 1),
    "extra_l3": ("bb1", 2),
    "extra_l4": ("bb1", 3),
    "extra_r1": ("bb2", 0),
    "extra_r2": ("bb2", 1),
    "extra_r3": ("bb2", 2),
    "extra_r4": ("bb2", 3),
}

# --- V2 Presets (based on Win 5 device defaults) ---

# Mouse mode (device default): start=delete, select=escape (V1 had none/none)
BUTTONS_DEFAULT = {
    "dpad_up": "mouse_wheelup",
    "dpad_down": "mouse_wheeldown",
    "dpad_left": "home",
    "dpad_right": "end",
    "a": "down",
    "b": "right",
    "x": "left",
    "y": "up",
    "ls_up": "w",
    "ls_down": "s",
    "ls_left": "a",
    "ls_right": "d",
    "ls": "space",
    "rs": "enter",
    "start": "delete",
    "select": "escape",
    "menu": "none",
}

# Gaming / WASD mode
BUTTONS_PHAWX = {
    "dpad_up": "up",
    "dpad_down": "down",
    "dpad_left": "left",
    "dpad_right": "right",
    "a": "space",
    "b": "leftctrl",
    "x": "z",
    "y": "leftalt",
    "ls_up": "w",
    "ls_down": "s",
    "ls_left": "a",
    "ls_right": "d",
    "ls": "leftshift",
    "rs": "enter",
    "start": "escape",
    "select": "enter",
    "menu": "none",
}

BUTTONS_TRIGGERS_DEFAULT = {
    "lb": "mouse_left",
    "rb": "mouse_right",
    "lt": "mouse_middle",
    "rt": "mouse_fast",
}

BUTTONS_TRIGGERS_STEAMOS = {
    "lb": "mouse_middle",
    "rb": "mouse_fast",
    "lt": "mouse_right",
    "rt": "mouse_left",
}

# Device default: BB1=leftctrl+leftshift macro, BB2=f3, hold=50ms
BACKBUTTONS_DEFAULT = {
    "buttons": {
        "extra_l1": "leftctrl",
        "extra_l2": "leftshift",
        "extra_l3": "none",
        "extra_l4": "none",
        "extra_r1": "f3",
        "extra_r2": "none",
        "extra_r3": "none",
        "extra_r4": "none",
    },
    "delays": {
        "extra_l1": 50,
        "extra_l2": 50,
        "extra_l3": 50,
        "extra_l4": 50,
        "extra_r1": 50,
        "extra_r2": 50,
        "extra_r3": 50,
        "extra_r4": 50,
    },
}

# HHD detection keys
BACKBUTTONS_HHD = {
    "buttons": {
        "extra_l1": "none",
        "extra_l2": "none",
        "extra_l3": "none",
        "extra_l4": "none",
        "extra_r1": "none",
        "extra_r2": "none",
        "extra_r3": "none",
        "extra_r4": "none",
    },
    "delays": {
        "extra_l1": 0,
        "extra_l2": 0,
        "extra_l3": 0,
        "extra_l4": 0,
        "extra_r1": 0,
        "extra_r2": 0,
        "extra_r3": 0,
        "extra_r4": 0,
    },
}


# --- V2 firmware version whitelist ---
# major_ver -> max minor_ver (inclusive)
# Win 5 reports X603K801
GM_SUPPORTED_VERSIONS = {6: 0x03}
EXT_SUPPORTED_VERSIONS = {8: 0x01}


def check_fwver(resp: bytes):
    """Parse and validate firmware version from 0x41 response.

    Returns (fwver_string). Raises on unsupported version."""
    xi_major, xi_minor = resp[11], resp[10]
    kb_major, kb_minor = resp[13], resp[12]
    fwver = f"X{xi_major}{xi_minor:02x}K{kb_major}{kb_minor:02x}"

    for k, v in GM_SUPPORTED_VERSIONS.items():
        if xi_major == k:
            assert (
                xi_minor <= v
            ), f"Unsupported gamepad firmware version {fwver} (up to X{k}{v:02x})"
            break
    else:
        raise ValueError(f"Unsupported gamepad major version {xi_major} in {fwver}")

    for k, v in EXT_SUPPORTED_VERSIONS.items():
        if kb_major == k:
            assert (
                kb_minor <= v
            ), f"Unsupported keyboard firmware version {fwver} (up to K{k}{v:02x})"
            break
    else:
        raise ValueError(f"Unsupported keyboard major version {kb_major} in {fwver}")

    return fwver


# --- V2 packet helpers ---


def _make_packet(cmd, size_byte=0, page_idx=0, data=b""):
    """Build a 64-byte V2 command packet with checksum at bytes 6-7."""
    pkt = bytearray(PKTSIZE)
    pkt[0] = 0x01  # report ID
    pkt[1] = cmd
    pkt[2] = size_byte
    pkt[4] = page_idx & 0xFF
    pkt[5] = (page_idx >> 8) & 0xFF
    for i, b in enumerate(data):
        if 8 + i < PKTSIZE:
            pkt[8 + i] = b
    chk = sum(pkt[8:PKTSIZE]) & 0xFFFF
    pkt[6] = chk & 0xFF
    pkt[7] = (chk >> 8) & 0xFF
    return bytes(pkt)


def _send(d: Device, pkt: bytes):
    """Send a V2 command via SET_REPORT Feature.

    On Linux, the V2 firmware requires feature reports for sending
    (see libOpenWinControls: hid_send_feature_report on non-Windows).
    Responses are read via GET_INPUT_REPORT.
    """
    d.send_feature_report(pkt)


def _recv(d: Device) -> bytes:
    """Receive a V2 response via GET_INPUT_REPORT."""
    resp = d.get_input_report(0x01, PKTSIZE)
    # Pad to PKTSIZE if the response is shorter
    if len(resp) < PKTSIZE:
        resp = resp + bytes(PKTSIZE - len(resp))
    return resp


def _init_read(d: Device):
    """V2 two-step init handshake for read operations."""
    # Init 1 (0x21)
    _send(d, _make_packet(0x21))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] == 0xAA, f"Init 1 failed: 0x{resp[8]:02x}"

    # Init 2 (0x2B) — only needed for reads
    _send(d, _make_packet(0x2B))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] == 0xAA, f"Init 2 failed: 0x{resp[8]:02x}"


def _init_write(d: Device):
    """V2 single-step init for write operations."""
    _send(d, _make_packet(0x21))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] == 0xAA, f"Init write failed: 0x{resp[8]:02x}"


# --- Read / Write ---


def _read_stream(d: Device) -> tuple[bytes, bytes]:
    """Read config via 0x44 streaming. Returns (header, cfg).

    Caller must have already initialized communication.
    """
    _send(d, _make_packet(0x44, size_byte=0x02, data=b"\x00\x04"))
    time.sleep(PAUSE)

    stream = bytearray()
    while True:
        resp = _recv(d)
        assert resp[1] == 0x44, f"Expected 0x44, got 0x{resp[1]:02x}"
        size = resp[2]
        stream.extend(resp[8 : 8 + min(size, DATA_PER_PKT)])
        if size < DATA_PER_PKT:
            break
        time.sleep(PAUSE)

    header = bytes(stream[:HEADER_SIZE])
    cfg = bytes(stream[HEADER_SIZE:])
    if len(cfg) < 1024:
        cfg = cfg + b"\xff" * (1024 - len(cfg))
    return header, cfg


def _read_fwver(d: Device) -> str:
    """Read and validate firmware version via 0x41 command."""
    _send(d, _make_packet(0x41))
    time.sleep(PAUSE)
    resp = _recv(d)
    if resp[1] != 0x41:
        return ""
    return check_fwver(resp)


def read_config(d: Device) -> tuple[str, bytes, bytes]:
    """Read config using V2 streaming protocol.

    Returns (fwver, transfer_header, config_bytes).
    The transfer_header must be saved and passed to write_config.
    """
    _init_read(d)
    header, cfg = _read_stream(d)

    logger.info(f"Reading Current Config from device.\nRead {len(cfg)} bytes, header: {header.hex()}")
    for off in range(0, len(cfg), 16):
        line = cfg[off : off + 16]
        if any(b != 0 and b != 0xFF for b in line):
            logger.info(f"  {off:4d}: {line.hex()}")

    fwver = _read_fwver(d)
    assert fwver, "Could not read firmware version"
    logger.info(f"Firmware: {fwver}")

    return fwver, header, cfg


def write_config(d: Device, fwver: str, header: bytes, cfg: bytes):
    """Write config using V2 streaming protocol with checksum verification.

    Safety flow (mirrors V1 write_config):
    1. Init write, verify handshake
    2. Stream config data to device RAM (0x43)
    3. Commit 1 (0x27) — device processes buffered data; verify not rejected
    4. Checksum gate: local sum(cfg) must match device-reported checksum
       before committing to EEPROM
    5. Commit 2 (0x22) — commit to EEPROM (ONLY if checksum matches)
    6. Verify + finalize (0x25 + 0x22) following GPD official app pattern
    """
    # Step 0: Verify firmware version hasn't changed since read
    fwver_new = _read_fwver(d)
    assert fwver_new == fwver, f"Firmware version changed: {fwver} -> {fwver_new}"
    logger.info(f"Firmware version: {fwver}")

    # Log config about to be committed
    logger.info(f"Config to commit (header: {header.hex()}):")
    for off in range(0, len(cfg[:1012]), 16):
        line = cfg[off : off + 16]
        if any(b != 0 and b != 0xFF for b in line):
            logger.info(f"  {off:4d}: {line.hex()}")

    # Step 1: Init write handshake
    _init_write(d)

    # Step 2: Stream write
    stream = bytearray(header) + bytearray(cfg[:1012])
    logger.info("Writing config...")
    offset = 0
    while offset < len(stream):
        remaining = len(stream) - offset
        size = min(remaining, DATA_PER_PKT)

        pkt = bytearray(PKTSIZE)
        pkt[0] = 0x01
        pkt[1] = 0x43
        pkt[2] = 0x38 if size == DATA_PER_PKT else size
        pkt[4] = offset & 0xFF
        pkt[5] = (offset >> 8) & 0xFF
        pkt[8 : 8 + size] = stream[offset : offset + size]
        chk = sum(pkt[8:PKTSIZE]) & 0xFFFF
        pkt[6] = chk & 0xFF
        pkt[7] = (chk >> 8) & 0xFF

        _send(d, bytes(pkt))
        offset += size

    # Step 3: Commit 1 (0x27) — prepare flash, returns device checksum
    _send(d, _make_packet(0x27, size_byte=0x02, data=b"\x00\x04"))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] != 0xE2, f"Commit 1 rejected (0x{resp[8]:02x}). Config NOT written."

    # Step 4: Checksum verification before EEPROM commit
    # V2 Commit 1 response: bytes 8-9 = stream size, bytes 10-11 = 16-bit
    # checksum over the full stream (header + cfg[:1012]).
    local_chk = sum(header + cfg[:1012]) & 0xFFFF
    device_chk = int.from_bytes(resp[10:12], "little")
    logger.info(f"Checksum: local=0x{local_chk:x} device=0x{device_chk:x}")
    if local_chk != device_chk:
        logger.error(
            f"Checksum MISMATCH: local=0x{local_chk:x} device=0x{device_chk:x}. "
            f"Aborting EEPROM commit to prevent corruption!"
        )
        logger.error(f"Commit 1 response: {resp.hex()}")
        raise AssertionError(
            f"Config checksum mismatch (local=0x{local_chk:x}, "
            f"device=0x{device_chk:x}). EEPROM commit aborted."
        )

    # Step 5: Commit 2 (0x22) — write to EEPROM (only reached if checksum matches)
    logger.info("Checksum verified. Committing to EEPROM...")
    _send(d, _make_packet(0x22))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] != 0xE2, f"Commit 2 rejected (0x{resp[8]:02x}). Config may be corrupt."

    # Step 6: Verify + finalize (GPD app pattern: init1 + 0x25 + 0x22)
    _init_write(d)
    _send(d, _make_packet(0x25, size_byte=0x04, data=b"\x00\x04"))
    time.sleep(PAUSE)
    resp = _recv(d)
    assert resp[8] != 0xE2, f"Verify rejected (0x{resp[8]:02x})."

    _send(d, _make_packet(0x22))

    logger.info("Config written and verified.")


# --- Back button helpers ---


def _recalc_bb(cfg: bytearray, bb_name: str):
    """Recalculate back button mode, slot count, and checksum."""
    base = BB_OFFSETS[bb_name]

    # Find highest active slot
    num = 0
    for i in range(32):
        slot = base + 4 + i * 6
        if slot + 6 > base + BB_REGION_SIZE:
            break
        if any(cfg[slot : slot + 6]):
            num = i + 1

    # Determine mode from slot contents
    has_xinput = False
    for i in range(num):
        slot = base + 4 + i * 6
        key = int.from_bytes(cfg[slot : slot + 2], "little")
        if key >= 0x8000:
            has_xinput = True

    # Use mode 0x00 for empty back buttons, 0x02 (macro) otherwise
    mode = 0x02
    if has_xinput:
        mode |= 0x04

    cfg[base] = mode
    cfg[base + 1] = num

    # Checksum = sum of NUM * 6 bytes of slot data
    slot_data = cfg[base + 4 : base + 4 + num * 6]
    chk = sum(slot_data) & 0xFFFF
    cfg[base + 2] = chk & 0xFF
    cfg[base + 3] = (chk >> 8) & 0xFF


# --- Public API (same ABI as wincontrols.py) ---


def update_config(
    buttons: dict[str, str] = {},
    delays: dict[str, int] = {},
    deadzones: dict[str, int] = {},
    rumble: str | None = None,
    rgb_mode: str | None = None,
    rgb_color: tuple[int, int, int] | None = None,
):
    devs = enumerate_unique(VID, PID, 0xFF00, 0x0001)
    assert devs, "No devices found."

    dev = devs[0]
    with Device(path=dev["path"]) as d:
        fwver, header, cfg = read_config(d)

    init_cfg = cfg
    cfg = bytearray(cfg)
    bb_modified = set()

    for k, v in buttons.items():
        assert v in ACTION_MAP, f"Unknown action {v}"
        action = ACTION_MAP[v]

        if k in KB_BUTTON_MAP:
            off = KB_BUTTON_MAP[k]
            cfg[off : off + 2] = action.to_bytes(2, "little")
        elif k in EXTRA_TO_BB:
            bb_name, slot_idx = EXTRA_TO_BB[k]
            slot = BB_OFFSETS[bb_name] + 4 + slot_idx * 6
            cfg[slot : slot + 2] = action.to_bytes(2, "little")
            bb_modified.add(bb_name)
        else:
            raise AssertionError(f"Unknown button {k}")

    for k, v in delays.items():
        assert k in EXTRA_TO_BB, f"Unknown delay {k}"
        bb_name, slot_idx = EXTRA_TO_BB[k]
        # hold_time is at offset +4 within the 6-byte slot
        slot = BB_OFFSETS[bb_name] + 4 + slot_idx * 6 + 4
        cfg[slot : slot + 2] = v.to_bytes(2, "little")
        bb_modified.add(bb_name)

    for bb in bb_modified:
        _recalc_bb(cfg, bb)

    deadzones = {k: min(max(v, -10), 10) for k, v in deadzones.items()}
    for k, v in deadzones.items():
        assert k in DEADZONE_MAP, f"Unknown deadzone {k}"
        cfg[DEADZONE_MAP[k] : DEADZONE_MAP[k] + 1] = v.to_bytes(
            1, "little", signed=True
        )

    if rumble is not None:
        assert rumble in RUMBLE_MODES, f"Unknown rumble mode {rumble}"
        cfg[SETTING_RUMBLE] = RUMBLE_MODES[rumble]

    if rgb_mode is not None:
        assert rgb_mode in RGB_MODES, f"Unknown rgb mode {rgb_mode}"
        cfg[SETTING_RGB_CONTROL] = RGB_MODES[rgb_mode]

    if rgb_color is not None:
        assert len(rgb_color) == 3, "RGB color must be a tuple of 3 integers"
        cfg[SETTING_RGB_RED] = rgb_color[0]
        cfg[SETTING_RGB_GREEN] = rgb_color[1]
        cfg[SETTING_RGB_BLUE] = rgb_color[2]

    if all(i == j for i, j in zip(cfg, init_cfg)):
        logger.info("No changes to apply. Skipping write.")
        return fwver

    with Device(path=dev["path"]) as d:
        write_config(d, fwver, header, bytes(cfg))

    return fwver


def explain_config():
    ACTION_MAP_REV = {v: k for k, v in ACTION_MAP.items()}
    RGB_MODES_REV = {v: k for k, v in RGB_MODES.items()}
    RUMBLE_MODES_REV = {v: k for k, v in RUMBLE_MODES.items()}

    devs = enumerate_unique(VID, PID, 0xFF00, 0x0001)
    assert devs, "No devices found."

    dev = devs[0]
    with Device(path=dev["path"]) as d:
        fwver, _, cfg = read_config(d)

    logger.info(f"\nFirmware: {fwver}")

    logger.info("\nButtons:")
    for k, v in KB_BUTTON_MAP.items():
        val = int.from_bytes(cfg[v : v + 2], "little")
        logger.info(f"  {k}: {ACTION_MAP_REV.get(val, f'0x{val:04x}')}")

    logger.info("\nBack Buttons:")
    for bb_name, bb_off in BB_OFFSETS.items():
        mode = cfg[bb_off]
        num = cfg[bb_off + 1]
        logger.info(f"  {bb_name}: mode=0x{mode:02x} slots={num}")
        for i in range(min(num, 32)):
            slot = bb_off + 4 + i * 6
            key = int.from_bytes(cfg[slot : slot + 2], "little")
            start = int.from_bytes(cfg[slot + 2 : slot + 4], "little")
            hold = int.from_bytes(cfg[slot + 4 : slot + 6], "little")
            key_name = ACTION_MAP_REV.get(key, f"0x{key:04x}")
            logger.info(f"    [{i}]: {key_name} start={start}ms hold={hold}ms")

    logger.info("\nDeadzones:")
    for k, v in DEADZONE_MAP.items():
        val = int.from_bytes(cfg[v : v + 1], "little", signed=True)
        logger.info(f"  {k}: {val}")

    logger.info(f"\nRumble: {RUMBLE_MODES_REV.get(cfg[SETTING_RUMBLE], 'unknown')}")

    rgb = cfg[SETTING_RGB_CONTROL]
    rgb_hex = f"#{cfg[SETTING_RGB_RED]:02x}{cfg[SETTING_RGB_GREEN]:02x}{cfg[SETTING_RGB_BLUE]:02x}"
    logger.info(f"RGB: {RGB_MODES_REV.get(rgb, f'0x{rgb:02x}')} {rgb_hex}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    explain_config()
