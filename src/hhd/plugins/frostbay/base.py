import logging
from threading import Event as TEvent
from time import sleep, time

from hhd.plugins import Config

logger = logging.getLogger(__name__)

FROSTBAY_NAME_PREFIXES = (
    "coolingsystem",
    "coolingdevice",
    "cooling",
)
FROSTBAY_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
FROSTBAY_SECONDARY_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
FROSTBAY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

STATE_MODE_IDX = 4
STATE_FLOW_ML_PER_MIN_START_IDX = 6
STATE_FLOW_ML_PER_MIN_END_IDX = 8
STATE_RUNNING_ACTIVITY_IDX = 12
STATE_WATER_TEMP_IN_IDX = 13
STATE_WATER_TEMP_OUT_IDX = 14

# state[4] mode byte values
MODE_OFF = 0x00
MODE_SMART = 0xFE
MODE_FIXED = 0xFF

# state[5] baseline for smart fan
SMART_FAN_BASE = 0x32

# Smart preset: (selector_a, selector_b, curve_bytes[23..40])
SMART_PRESETS = {
    "silent": (0x06, 0x00, bytes.fromhex("1E18201C2124222C233024342538263C2846")),
    "soft":   (0x06, 0xF0, bytes.fromhex("1E222026212E2236233A243E254226462850")),
    "strong": (0x08, 0x10, bytes.fromhex("1E2C20302138224023442448254C26502864")),
}

CHUNK_DELAY_S = 0.02
POST_WRITE_DELAY_S = 0.3
RETRY_DELAY_S = 1.0
DBUS_SERVICE = "org.bluez"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_DEVICE_IFACE = "org.bluez.Device1"
DBUS_GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
READ_TIMEOUT_S = 15.0
WRITE_TIMEOUT_S = 15.0
TELEMETRY_POLL_INTERVAL_S = 2.0
ON_RETRY_DELAY_S = 0.5
MAX_ON_WRITE_RETRIES = 10


def _to_bool(value) -> bool:
    return bool(value)


def _uuid_set(values) -> set[str]:
    return {str(value).lower() for value in values or []}


def _get_managed_objects():
    import dbus

    bus = dbus.SystemBus()
    obj = bus.get_object(DBUS_SERVICE, "/")
    om = dbus.Interface(obj, DBUS_OBJECT_MANAGER_IFACE)
    return om.GetManagedObjects()


def _find_characteristic_path(objects, device_path: str, uuid: str) -> str | None:
    prefix = f"{device_path}/"
    target_uuid = uuid.lower()
    for path, ifaces in sorted(objects.items()):
        if not str(path).startswith(prefix):
            continue
        props = ifaces.get(DBUS_GATT_CHARACTERISTIC_IFACE)
        if not props:
            continue
        if str(props.get("UUID", "")).lower() == target_uuid:
            return str(path)
    return None


def _device_name(props) -> str:
    return str(props.get("Name") or props.get("Alias") or "")


def _frostbay_name_score(props) -> int:
    name = _device_name(props).strip().lower()
    if not name:
        return 0

    for idx, prefix in enumerate(FROSTBAY_NAME_PREFIXES):
        if name.startswith(prefix):
            return len(FROSTBAY_NAME_PREFIXES) - idx

    return 0


def _system_state() -> dict[str, object]:
    objects = _get_managed_objects()
    candidates: list[dict[str, object]] = []

    for path, ifaces in sorted(objects.items()):
        path_str = str(path)
        props = ifaces.get(DBUS_DEVICE_IFACE)
        if not props:
            continue

        uuids = _uuid_set(props.get("UUIDs", []))
        name_score = _frostbay_name_score(props)
        has_primary_service = FROSTBAY_SERVICE_UUID in uuids
        has_secondary_service = FROSTBAY_SECONDARY_SERVICE_UUID in uuids
        if not name_score and not has_primary_service and not has_secondary_service:
            continue

        connected = _to_bool(props.get("Connected", False))
        services_resolved = _to_bool(props.get("ServicesResolved", False))
        char_path = _find_characteristic_path(objects, path_str, FROSTBAY_UUID)
        candidate = {
            "path": path_str,
            "adapter": path_str.split("/")[3],
            "name": _device_name(props),
            "address": str(props.get("Address", "")),
            "known": True,
            "paired": _to_bool(props.get("Paired", False)),
            "bonded": _to_bool(props.get("Bonded", False)),
            "trusted": _to_bool(props.get("Trusted", False)),
            "connected": connected,
            "services_resolved": services_resolved,
            "uuids": uuids,
            "has_service": has_primary_service,
            "char_path": char_path,
        }
        candidate["score"] = (
            name_score * 16
            + int(candidate["connected"]) * 8
            + int(candidate["services_resolved"]) * 4
            + int(candidate["has_service"]) * 2
            + int(candidate["char_path"] is not None)
        )
        candidates.append(candidate)

    if not candidates:
        return {
            "path": None,
            "adapter": None,
            "name": None,
            "address": None,
            "known": False,
            "paired": False,
            "bonded": False,
            "trusted": False,
            "connected": False,
            "services_resolved": False,
            "uuids": set(),
            "has_service": False,
            "char_path": None,
        }

    candidates.sort(key=lambda item: (item["score"], item["path"]), reverse=True)
    winner = dict(candidates[0])
    winner.pop("score", None)
    return winner


def _read_char(char_path: str) -> bytes:
    import dbus

    bus = dbus.SystemBus()
    obj = bus.get_object(DBUS_SERVICE, char_path)
    char = dbus.Interface(obj, DBUS_GATT_CHARACTERISTIC_IFACE)
    return bytes(char.ReadValue({}, timeout=READ_TIMEOUT_S))


def _read_state(char_path: str) -> bytearray:
    longest = bytearray()
    for attempt in range(3):
        try:
            raw = bytearray(_read_char(char_path))
            if len(raw) > len(longest):
                longest = raw
            if len(raw) >= 59:
                if len(raw) < 64:
                    raw.extend(b"\x00" * (64 - len(raw)))
                return raw
            raise RuntimeError(f"Short read: {len(raw)} bytes")
        except Exception as e:
            logger.warning(f"Read attempt {attempt + 1} failed: {e}")

    if len(longest) >= 59:
        if len(longest) < 64:
            longest.extend(b"\x00" * (64 - len(longest)))
        return longest

    raise RuntimeError(f"Unable to read full Frostbay state (max {len(longest)} bytes)")


def _running_state_label(state: bytearray) -> str:
    if _is_running(state):
        return "ON"
    return "OFF"


def _is_running(state: bytearray) -> bool:
    return state[STATE_MODE_IDX] != MODE_OFF and state[STATE_RUNNING_ACTIVITY_IDX] > 0


def _format_temp(value: int) -> str:
    return f"{value} C"


def _flow_ml_per_min(state: bytearray) -> int:
    raw_flow = int.from_bytes(
        state[STATE_FLOW_ML_PER_MIN_START_IDX:STATE_FLOW_ML_PER_MIN_END_IDX],
        byteorder="big",
    )
    return round(raw_flow / 10)


def _decode_flow_ml_per_min(state: bytearray) -> str:
    flow = _flow_ml_per_min(state)
    return f"{flow} mL/min"


def _should_retry_on_write(target: tuple, state: bytearray) -> bool:
    return target[0] != "off" and not _is_running(state) and _flow_ml_per_min(state) > 0


def _decode_telemetry(state: bytearray) -> dict[str, str]:
    return {
        "running_state": _running_state_label(state),
        "flow": _decode_flow_ml_per_min(state),
        "water_temp_in": _format_temp(state[STATE_WATER_TEMP_IN_IDX]),
        "water_temp_out": _format_temp(state[STATE_WATER_TEMP_OUT_IDX]),
    }


def _set_telemetry(telemetry_ref: dict[str, str], **values: str):
    telemetry_ref.update(values)


def _write_state(char_path: str, state: bytearray):
    import dbus

    payload = bytearray(58)
    payload[0] = 0x02
    payload[1:] = state[2:59]

    chunk_1 = bytearray(20)
    chunk_1[0] = 0x1C
    chunk_1[1:] = payload[0:19]

    chunk_2 = bytearray(20)
    chunk_2[0] = 0x2C
    chunk_2[1:] = payload[19:38]

    chunk_3 = bytearray(20)
    chunk_3[0] = 0x3C
    tail = payload[38:57]
    chunk_3[1:1+len(tail)] = tail

    bus = dbus.SystemBus()
    obj = bus.get_object(DBUS_SERVICE, char_path)
    char = dbus.Interface(obj, DBUS_GATT_CHARACTERISTIC_IFACE)

    for attempt in range(3):
        try:
            for chunk in (chunk_1, chunk_2, chunk_3):
                char.WriteValue(
                    dbus.Array(chunk, signature=dbus.Signature("y")),
                    {},
                    timeout=WRITE_TIMEOUT_S,
                )
                if chunk is not chunk_3:
                    sleep(CHUNK_DELAY_S)
            sleep(POST_WRITE_DELAY_S)
            return
        except Exception as e:
            logger.warning(f"Write attempt {attempt+1} failed: {e}")
            if attempt < 2:
                sleep(0.5)
            else:
                raise


# ── settings helpers ───────────────────────────────────────────────────────────

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _target_from_conf(conf: Config, is_on: bool) -> tuple:
    if not is_on:
        return ("off",)
    mode = conf.get("fan.mode", "auto")
    preset = conf.get("fan.auto.preset", "soft")
    if preset not in SMART_PRESETS:
        preset = "soft"
    fan = _clamp(conf.get("fan.manual.percent", 50), 0, 100)
    pump = _clamp(conf.get("pump", 80), 50, 100)
    return (mode, preset, fan, pump)


def _apply_target_to_state(state: bytearray, target: tuple):
    if target[0] == "off":
        state[4] = MODE_OFF
        return
    mode_str, preset, fan, pump = target
    if mode_str == "auto":
        sel_a, sel_b, curve = SMART_PRESETS[preset]
        state[4] = MODE_SMART
        state[5] = SMART_FAN_BASE
        state[6] = sel_a
        state[7] = sel_b
        state[8] = pump
        state[23:41] = curve
    else:
        state[4] = MODE_FIXED
        state[5] = fan
        state[8] = pump


# ── main plugin loop ───────────────────────────────────────────────────────────

def plugin_run(
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    want_on: TEvent,
    force_on_apply: TEvent,
    status_ref: list,
    telemetry_ref: dict[str, str],
):
    logger.info("Frostbay plugin worker started")

    active_device_path: str | None = None
    active_char_path: str | None = None
    last_target: tuple | None = None
    last_telemetry_target: tuple | None = None
    last_telemetry_poll = 0.0

    def do_read() -> bytearray:
        if not active_char_path:
            raise RuntimeError("Frostbay characteristic is not ready")
        return _read_state(active_char_path)

    def do_write(state: bytearray):
        if not active_char_path:
            raise RuntimeError("Frostbay characteristic is not ready")
        _write_state(active_char_path, state)

    def write_target(state: bytearray, target: tuple) -> bytearray:
        _apply_target_to_state(state, target)
        do_write(state)

        if target[0] == "off":
            return state

        verified_state = do_read()
        _set_telemetry(telemetry_ref, **_decode_telemetry(verified_state))

        retry_count = 0
        while retry_count < MAX_ON_WRITE_RETRIES and _should_retry_on_write(target, verified_state):
            retry_count += 1
            logger.warning(
                "Frostbay reported OFF after ON write despite flow %s; retrying ON write (%s/%s)",
                _decode_flow_ml_per_min(verified_state),
                retry_count,
                MAX_ON_WRITE_RETRIES,
            )
            retry_state = bytearray(verified_state)
            _apply_target_to_state(retry_state, target)
            do_write(retry_state)
            sleep(ON_RETRY_DELAY_S)
            verified_state = do_read()
            _set_telemetry(telemetry_ref, **_decode_telemetry(verified_state))

        return verified_state

    def is_connected() -> bool:
        if not active_device_path or not active_char_path:
            return False
        state = _system_state()
        return (
            state["path"] == active_device_path
            and state["char_path"] == active_char_path
            and state["connected"]
            and state["services_resolved"]
        )

    def reset():
        nonlocal active_device_path, active_char_path, last_target, last_telemetry_target, last_telemetry_poll
        active_device_path = None
        active_char_path = None
        last_target = None
        last_telemetry_target = None
        last_telemetry_poll = 0.0
        _set_telemetry(
            telemetry_ref,
            running_state="Unknown",
            flow="--",
            water_temp_in="--",
            water_temp_out="--",
        )

    try:
        wait_count = 0
        while not should_exit.is_set():
            state = _system_state()

            if not state["known"]:
                status_ref[0] = "Waiting for device..."
                if active_char_path:
                    reset()
                if wait_count % 6 == 0:
                    logger.info("Frostbay device is not visible to BlueZ yet.")
                wait_count += 1
                should_exit.wait(timeout=5.0)
                continue

            if not state["connected"]:
                status_ref[0] = "Waiting for connection..."
                if active_char_path:
                    reset()
                if wait_count % 6 == 0:
                    logger.info(
                        "Frostbay is visible but not transport-connected yet. "
                        f"Waiting for OS connection (paired={'yes' if state['paired'] else 'no'}, "
                        f"trusted={'yes' if state['trusted'] else 'no'})."
                    )
                wait_count += 1
                should_exit.wait(timeout=2.0)
                continue

            if not state["services_resolved"] or not state["has_service"]:
                status_ref[0] = "Waiting for services..."
                if active_char_path:
                    reset()
                if wait_count % 6 == 0:
                    uuids = sorted(state["uuids"])
                    logger.info(
                        "Frostbay is connected but services are not ready yet. "
                        f"resolved={'yes' if state['services_resolved'] else 'no'} UUIDs={uuids}"
                    )
                wait_count += 1
                should_exit.wait(timeout=2.0)
                continue

            if not state["char_path"]:
                status_ref[0] = "Waiting for FFE1..."
                if active_char_path:
                    reset()
                if wait_count % 6 == 0:
                    logger.info(
                        f"Frostbay services are present on {state['adapter']} but FFE1 is not ready yet."
                    )
                wait_count += 1
                should_exit.wait(timeout=RETRY_DELAY_S)
                continue

            if active_char_path != state["char_path"] or active_device_path != state["path"]:
                wait_count = 0
                active_device_path = state["path"]
                active_char_path = state["char_path"]
                last_target = None
                last_telemetry_target = None
                last_telemetry_poll = 0.0
                logger.info(
                    "Frostbay OS session is ready; binding directly to "
                    f"{active_char_path} on {state['adapter']} "
                    f"for {state['name'] or 'Frostbay'} ({state['address'] or 'unknown address'})."
                )
                status_ref[0] = "Connected"
                should_exit.wait(timeout=0.5)

                if should_exit.is_set():
                    break

                state = _system_state()
                if (
                    state["path"] != active_device_path
                    or state["char_path"] != active_char_path
                    or not state["connected"]
                    or not state["services_resolved"]
                ):
                    logger.warning("OS readiness changed before Frostbay path bind completed; waiting again.")
                    reset()
                    continue

            is_on = want_on.is_set()
            if not is_on:
                force_on_apply.clear()
            status_ref[0] = "Connected" if is_on else "Connected (off)"

            if not is_connected():
                logger.warning("BlueZ Frostbay session changed, resetting bound characteristic path...")
                reset()
                continue

            state = _system_state()
            if (
                state["path"] != active_device_path
                or state["char_path"] != active_char_path
                or not state["connected"]
                or not state["services_resolved"]
            ):
                logger.warning("OS Frostbay session is no longer ready, dropping characteristic binding...")
                reset()
                continue

            target = _target_from_conf(conf, is_on)
            now = time()
            sample_due = (
                last_telemetry_target is None
                or target != last_telemetry_target
                or (now - last_telemetry_poll) >= TELEMETRY_POLL_INTERVAL_S
            )

            current_state = None
            if sample_due:
                try:
                    current_state = do_read()
                    _set_telemetry(telemetry_ref, **_decode_telemetry(current_state))
                    last_telemetry_target = target
                    last_telemetry_poll = now
                except Exception as e:
                    logger.warning(f"Telemetry read error: {e}, forcing reset")
                    status_ref[0] = "Error — resetting"
                    reset()
                    continue

            running_state = telemetry_ref["running_state"]
            status_ref[0] = f"Connected ({running_state})"

            force_apply = is_on and force_on_apply.is_set()
            if target != last_target or force_apply:
                logger.info(f"Applying target: {target}")
                try:
                    if current_state is None:
                        current_state = do_read()
                        _set_telemetry(telemetry_ref, **_decode_telemetry(current_state))
                        last_telemetry_target = target
                        last_telemetry_poll = now
                    current_state = write_target(current_state, target)
                    last_telemetry_target = target
                    last_telemetry_poll = time()
                    last_target = target
                    if force_apply:
                        force_on_apply.clear()
                except Exception as e:
                    logger.warning(f"Read/write error: {e}, forcing reset")
                    status_ref[0] = "Error — resetting"
                    reset()
                    continue

            updated.wait(timeout=2.0)
            updated.clear()

    except Exception as e:
        logger.exception(f"Fatal Frostbay error: {e}")
    finally:
        logger.info("Frostbay plugin worker stopping")
        reset()
