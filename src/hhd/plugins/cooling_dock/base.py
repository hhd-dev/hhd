import asyncio
import logging
import os
import threading
import time
from dataclasses import replace
from typing import Sequence

from hhd.plugins import Config, Context, Emitter, HHDPlugin, load_relative_yaml
from hhd.plugins.settings import HHDSettings

logger = logging.getLogger(__name__)

SUPPORTED_PRODUCTS = ("ONEXPLAYER SUPER X", "ONEXPLAYER APEX")

SCAN_BACKOFF_MIN = 5
SCAN_BACKOFF_MAX = 15
SCAN_BACKOFF_FACTOR = 2
GATT_WATCHDOG_TIMEOUT = 20
GATT_OP_TIMEOUT = 10
SYNC_RETRY_MAX = 3
RECONNECT_DELAY = 2
SYNC_RETRY_DELAY = 2
SYNC_READ_INTERVAL = 5  # >2s to avoid firmware BLE exhaustion
DOCK_RUNNING_GRACE = 10  # grace before dropping dock_running on BLE drops

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice

    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

from .protocol import (CHAR_UUID, CHUNK_DELAY_S, DEVICE_NAME, NOTIFY_UUID,
                       POST_WRITE_DELAY_S, SERVICE_UUID, TOTAL_BYTES,
                       WRITE_CMD, WRITE_RETRY_DELAY_S, WRITE_RETRY_MAX,
                       CoolingStatus, DockMode, build_write_chunks)


def get_cpu_temp() -> float:
    highest = 0.0
    try:
        hwmon_dir = "/sys/class/hwmon"
        if not os.path.exists(hwmon_dir):
            return highest
        for hwmon in os.listdir(hwmon_dir):
            path = os.path.join(hwmon_dir, hwmon)
            try:
                with open(os.path.join(path, "name"), "r") as f:
                    name = f.read().strip()
                if name in ("k10temp", "oxpec", "amdgpu"):
                    for file in os.listdir(path):
                        if file.startswith("temp") and file.endswith("_input"):
                            with open(os.path.join(path, file), "r") as f:
                                temp = int(f.read().strip()) / 1000.0
                                if temp > highest:
                                    highest = temp
            except Exception:
                continue
    except Exception:
        pass
    return highest


def fan_pct_for_temp(temp: float, curve: list[tuple[int, int]]) -> int:
    if not curve:
        return 0
    sorted_curve = sorted(curve, key=lambda x: x[1])
    if temp <= sorted_curve[0][1]:
        return sorted_curve[0][0]
    for i in range(1, len(sorted_curve)):
        if temp <= sorted_curve[i][1]:
            t0, f0 = sorted_curve[i - 1][1], sorted_curve[i - 1][0]
            t1, f1 = sorted_curve[i][1], sorted_curve[i][0]
            if t1 == t0:
                return f1
            ratio = (temp - t0) / (t1 - t0)
            return int(f0 + ratio * (f1 - f0))
    return sorted_curve[-1][0]


class CoolingDockPlugin(HHDPlugin):
    name = "cooling_dock"
    priority = 20
    log = "dock"

    def __init__(self) -> None:
        self.running = False
        self.thread = None
        self.conf_lock = threading.Lock()
        self.conf = None
        self.enabled = False
        self.mode = "auto"
        self.fan_curve = self._default_curve()
        self.rgb_enable = True
        self.rgb_mode = 1
        self.rgb_level = 3
        self._last_fan_pct = -1
        self._dock_running = False
        self._status = "Disconnected"
        self._fan_progress = None
        self._scan_delay = SCAN_BACKOFF_MIN
        self._last_gatt_read = 0.0
        self._mac_address = ""
        self._is_water_cooled = False
        self._force_reconnect = False
        self._scan_requested = False
        self._discovered_macs = {"": "None"}
        self._last_write_target = None
        self._last_write_time = 0.0
        self._last_connected_time = 0.0
        self._last_disconnect_time = None

    def _default_curve(self) -> list[tuple[int, int]]:
        return [(0, 40), (30, 50), (50, 60), (70, 70), (85, 80)]

    def open(self, emit: Emitter, context: Context):
        self.emit = emit
        if not BLEAK_AVAILABLE:
            logger.warning("Bleak not available, Cooling Dock plugin disabled.")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def close(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

    def settings(self) -> HHDSettings:
        base = {"cooling_dock": {"dock": load_relative_yaml("settings.yml")}}
        if not BLEAK_AVAILABLE:
            base["cooling_dock"]["dock"]["children"]["enabled"][
                "hint"
            ] = "Bleak is not installed. Install with: pip install bleak"
        else:
            with self.conf_lock:
                opts = self._discovered_macs.copy()
                if self._mac_address and self._mac_address not in opts:
                    opts[self._mac_address] = (
                        f"CoolingSystem_ONEC1 ({self._mac_address})"
                    )
                base["cooling_dock"]["dock"]["children"]["mac_address"][
                    "options"
                ] = opts

                # Hide controls when disabled or no dock selected
                if not self.enabled or not self._mac_address:
                    children = base["cooling_dock"]["dock"]["children"]
                    for key in ["mode", "fan_curve", "rgb", "status", "fan_progress", "forget_dock"]:
                        if key in children:
                            del children[key]

        return base

    def update(self, conf: Config):
        try:
            dock_conf = conf["cooling_dock.dock"]
        except Exception:
            return

        settings_dirty = False
        with self.conf_lock:
            self.conf = conf

            old_enabled = self.enabled
            old_mac = self._mac_address

            self.enabled = dock_conf.get("enabled", True)
            self.mode = dock_conf.get("mode", "auto")

            curve = []
            for i in range(1, 6):
                t = dock_conf.get(f"fan_curve.t{i}", None)
                f = dock_conf.get(f"fan_curve.f{i}", None)
                if t is not None and f is not None:
                    curve.append((int(f), int(t)))
            if curve:
                self.fan_curve = curve

            self.rgb_enable = dock_conf.get("rgb.enable", True)
            self.rgb_mode = int(dock_conf.get("rgb.mode", 1))
            self.rgb_level = int(dock_conf.get("rgb.level", 3))

            self._mac_address = dock_conf.get("mac_address", "")

            if self.enabled != old_enabled or self._mac_address != old_mac:
                settings_dirty = True

            if conf.get("cooling_dock.dock.forget_dock", False):
                conf["cooling_dock.dock.forget_dock"] = False
                self._forget_bluez_device()
                self._mac_address = ""
                conf["cooling_dock.dock.mac_address"] = ""
                self._force_reconnect = True
                settings_dirty = True


            if conf.get("cooling_dock.dock.scan_dock", False):
                conf["cooling_dock.dock.scan_dock"] = False
                self._scan_requested = True
                self._force_reconnect = True

            conf["cooling_dock.dock_running"] = self._dock_running
            conf["cooling_dock.dock.status"] = self._status
            conf["cooling_dock.dock.fan_progress"] = self._fan_progress


        emit = getattr(self, "emit", None)
        if settings_dirty and emit:
            emit({"type": "settings"})

    def _publish_dock_running(self, running: bool):
        with self.conf_lock:
            conf = self.conf
            if running == self._dock_running:
                return
            self._dock_running = running
            if conf is not None:
                conf["cooling_dock.dock_running"] = running

    def _publish_status(self, status: str, fan_progress: dict | None):
        with self.conf_lock:
            conf = self.conf
            if status == self._status and fan_progress == self._fan_progress:
                return
            self._status = status
            self._fan_progress = fan_progress
            if conf is not None:
                conf["cooling_dock.dock.status"] = status
                conf["cooling_dock.dock.fan_progress"] = fan_progress

    def _publish_disconnected_if_stale(self):
        if (
            self._last_connected_time
            and time.time() - self._last_connected_time > DOCK_RUNNING_GRACE
        ):
            self._publish_dock_running(False)
            self._publish_status("Disconnected", None)

    async def _write_state(self, client, state: bytearray):
        """Write state to dock using chunked protocol (3x20-byte frames)."""
        chunks = build_write_chunks(state)
        last_error = None
        for attempt in range(WRITE_RETRY_MAX):
            try:
                for chunk in chunks:
                    await asyncio.wait_for(
                        client.write_gatt_char(CHAR_UUID, chunk, response=True),
                        timeout=GATT_OP_TIMEOUT,
                    )
                    await asyncio.sleep(CHUNK_DELAY_S)
                await asyncio.sleep(POST_WRITE_DELAY_S)
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Cooling Dock chunked write failed "
                    f"({attempt + 1}/{WRITE_RETRY_MAX}): {e}"
                )
                if attempt < WRITE_RETRY_MAX - 1:
                    await asyncio.sleep(WRITE_RETRY_DELAY_S)
        raise last_error if last_error else RuntimeError("write failed")

    def _run_loop(self):
        asyncio.run(self._async_loop())

    async def _async_loop(self):
        while self.running:
            if not self.enabled:
                self._publish_dock_running(False)
                self._publish_status("Disconnected", None)
                self._scan_delay = SCAN_BACKOFF_MIN
                await asyncio.sleep(5)
                continue

            if not self._mac_address and not self._scan_requested:
                self._publish_dock_running(False)
                self._publish_status("No dock selected", None)
                self._scan_delay = SCAN_BACKOFF_MIN
                await asyncio.sleep(2)
                continue
            try:
                self._force_reconnect = False
                await self._connect_and_sync()
            except Exception as e:
                logger.error(f"Cooling Dock error: {e}")
                if self.running:
                    for _ in range(5):
                        if (
                            not self.running
                            or self._force_reconnect
                            or self._scan_requested
                        ):
                            break
                        await asyncio.sleep(1)

    async def _connect_and_sync(self):

        self._publish_disconnected_if_stale()

        ble_device = await self._find_dock()
        if not ble_device:
            logger.info(f"Cooling Dock not found, retrying in {self._scan_delay}s...")
            self._publish_disconnected_if_stale()
            delay = self._scan_delay

            self._scan_delay = min(
                self._scan_delay * SCAN_BACKOFF_FACTOR, SCAN_BACKOFF_MAX
            )

            for _ in range(delay):
                if not self.running or self._force_reconnect or self._scan_requested:
                    break
                await asyncio.sleep(1)
            return


        self._scan_delay = SCAN_BACKOFF_MIN

        addr = ble_device.address
        logger.info(f"Connecting to Cooling Dock at {addr}...")


        disconnected_event = asyncio.Event()

        def _on_disconnect(c):
            logger.info("Cooling Dock BLE link lost (disconnected callback)")
            disconnected_event.set()

        client = BleakClient(
            ble_device, timeout=15, disconnected_callback=_on_disconnect
        )

        for attempt in range(3):
            try:
                await client.connect()
                break
            except Exception as e:
                if attempt == 2:
                    logger.warning("Connection failed after 3 attempts, clearing BlueZ bond to self-heal.")
                    self._remove_stale_bond(addr)
                    raise
                logger.warning(f"Cooling Dock connect retry ({attempt + 1}/3): {e}")
                await asyncio.sleep(2)
        if not client.is_connected:
            logger.warning("Failed to connect to Cooling Dock")
            self._publish_disconnected_if_stale()
            await asyncio.sleep(5)
            return

        logger.info("Cooling Dock connected!")
        self._publish_status("Connected", None)
        self._last_gatt_read = time.time()
        now = time.time()

        if self._last_disconnect_time:
            gap = now - self._last_disconnect_time
            logger.info(f"BLE reconnect after {gap:.1f}s gap")
            self._last_disconnect_time = None
        self._last_connected_time = now


        if not self._mac_address:
            with self.conf_lock:
                self._mac_address = addr
                if self.conf is not None:
                    self.conf["cooling_dock.dock.mac_address"] = addr

        # Register MAC for UI without emitting settings (avoids reload storm)
        with self.conf_lock:
            if addr not in self._discovered_macs:
                self._discovered_macs[addr] = f"CoolingSystem_ONEC1 ({addr})"

        consecutive_errors = 0
        while (
            self.running
            and client.is_connected
            and not self._force_reconnect
            and not disconnected_event.is_set()
        ):

            if time.time() - self._last_gatt_read > GATT_WATCHDOG_TIMEOUT:
                logger.warning(
                    f"Dock GATT read timeout ({GATT_WATCHDOG_TIMEOUT}s), "
                    f"assuming disconnected."
                )
                break

            try:
                current = await asyncio.wait_for(
                    client.read_gatt_char(CHAR_UUID), timeout=GATT_OP_TIMEOUT
                )
                self._last_gatt_read = time.time()
                status = CoolingStatus.from_bytes(current)


                if status.pump_speed_percent > 0 or status.water_flow > 0:
                    self._is_water_cooled = True

                self._publish_dock_running(
                    status.fan_speed > 0 or status.fan_speed_percent > 0
                )

                if status.mode == 0:
                    status_str = "Connected - Stopped"
                    ui_fan_pct = 0
                elif self._is_water_cooled:
                    status_str = (
                        f"Connected (Water) - Fan {status.fan_speed_percent}% "
                        f"Pump {status.pump_speed_percent}%"
                    )
                    ui_fan_pct = status.fan_speed_percent
                else:
                    status_str = (
                        f"Connected (Air) - Fan {status.fan_speed_percent}% "
                        f"({status.fan_speed} RPM)"
                    )
                    ui_fan_pct = status.fan_speed_percent

                self._publish_status(
                    status_str,
                    {
                        "value": ui_fan_pct,
                        "max": 100,
                        "unit": "%",
                        "text": "Dock Fan",
                    },
                )

                with self.conf_lock:
                    mode = self.mode
                    curve = list(self.fan_curve)
                    rgb_en = self.rgb_enable
                    rgb_m = self.rgb_mode
                    rgb_lvl = self.rgb_level

                payload = bytearray(current)
                payload[1] = WRITE_CMD

                if mode == "auto":
                    temp = get_cpu_temp()
                    fan_pct = fan_pct_for_temp(temp, curve)
                    payload[4] = int(DockMode.AUTO)
                    payload[15] = 0xFE
                    idx = 23
                    for f, t in curve:
                        if idx + 1 < len(payload):
                            payload[idx] = f
                            payload[idx + 1] = t
                            idx += 2
                    logger.debug(
                        f"Auto: temp={temp:.1f}C fan={fan_pct}% "
                        f"(dock reports {status.fan_speed} RPM)"
                    )
                else:
                    try:
                        mode_val = int(mode)
                    except ValueError:
                        mode_val = int(DockMode.AUTO)
                    payload[4] = mode_val

                payload[16] = rgb_m
                payload[17] = 1 if rgb_en else 0
                payload[19] = rgb_lvl

                # Only write on change
                target = (mode, tuple(curve), rgb_en, rgb_m, rgb_lvl)
                now = time.time()
                target_changed = target != self._last_write_target
                if target_changed:
                    logger.info(f"Writing to dock: changed={target_changed}")
                    await self._write_state(client, payload)
                    self._last_write_target = target
                    self._last_write_time = now

                consecutive_errors = 0
                await asyncio.sleep(SYNC_READ_INTERVAL)

            except asyncio.TimeoutError:
                consecutive_errors += 1
                logger.warning(
                    f"Cooling Dock GATT timeout "
                    f"({consecutive_errors}/{SYNC_RETRY_MAX})"
                )
                if consecutive_errors >= SYNC_RETRY_MAX:
                    logger.error("Too many GATT timeouts, disconnecting.")
                    break
                await asyncio.sleep(SYNC_RETRY_DELAY)

            except Exception as e:
                consecutive_errors += 1
                logger.warning(
                    f"Cooling Dock sync error ({consecutive_errors}/"
                    f"{SYNC_RETRY_MAX}): {e}"
                )
                if consecutive_errors >= SYNC_RETRY_MAX:
                    logger.error("Too many sync errors, disconnecting.")
                    break
                await asyncio.sleep(SYNC_RETRY_DELAY)

        try:
            await client.disconnect()
        except Exception:
            pass

        self._force_reconnect = False
        self._last_disconnect_time = time.time()
        # Grace period handles dock_running; pause for BlueZ cleanup
        for _ in range(RECONNECT_DELAY):
            if not self.running or self._force_reconnect or self._scan_requested:
                break
            await asyncio.sleep(1)

    async def _bluez_start_discovery(self, target_mac: str | None, timeout: int = 10):
        """Trigger BlueZ to scan for BLE devices via D-Bus and wait until found."""
        try:
            import dbus

            bus = dbus.SystemBus()
            adapter = dbus.Interface(
                bus.get_object("org.bluez", "/org/bluez/hci0"), "org.bluez.Adapter1"
            )
            try:
                adapter.StartDiscovery()
            except dbus.DBusException as e:
                if e.get_dbus_name() != "org.bluez.Error.InProgress":
                    raise


            for _ in range(timeout):
                if not self.running:
                    break
                device = self._find_dock_in_bluez_objects(target_mac)
                if device:
                    break
                await asyncio.sleep(1)

            try:
                adapter.StopDiscovery()
            except dbus.DBusException:
                pass
        except Exception as e:
            logger.debug(f"BlueZ start discovery failed: {e}")

    def _find_dock_in_bluez_objects(
        self, target_mac: str | None = None
    ) -> BLEDevice | None:
        """Query BlueZ D-Bus for the dock (finds bonded/non-advertising devices)."""
        try:
            import dbus

            bus = dbus.SystemBus()
            obj = bus.get_object("org.bluez", "/")
            om = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()

            for path, ifaces in objects.items():
                props = ifaces.get("org.bluez.Device1")
                if not props:
                    continue

                name = str(props.get("Name", props.get("Alias", "")))
                mac = str(props.get("Address", "")).upper()

                if target_mac and mac != target_mac.upper():
                    continue

                name_match = "Cooling" in name
                mac_match = "C8:17:17" in mac

                if not target_mac and not (name_match or mac_match):
                    continue

                logger.info(f"Found dock in BlueZ D-Bus: {name} ({mac})")
                return BLEDevice(mac, name, {"path": str(path)})
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"BlueZ D-Bus object lookup failed: {e}")
        return None

    async def _find_dock(self) -> BLEDevice | None:
        try:
            with self.conf_lock:
                scan_req = self._scan_requested
                self._scan_requested = False

            if scan_req:
                self._publish_status("Scanning...", None)

            target_mac = self._mac_address.upper() if self._mac_address else None

            if not target_mac and not scan_req:
                return None

            device = self._find_dock_in_bluez_objects(target_mac)
            if device:

                if scan_req:
                    await self._populate_dropdown()
                return device

            scan_timeout = 10
            await self._bluez_start_discovery(target_mac, timeout=scan_timeout)

            if scan_req:
                await self._populate_dropdown()

            device = self._find_dock_in_bluez_objects(target_mac)
            if device:
                return device


            if target_mac:
                device = await BleakScanner.find_device_by_address(
                    target_mac, timeout=5
                )
                if device:
                    return device

            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
            return device

        except Exception as e:
            logger.debug(f"BLE scan error: {e}")
        return None

    async def _populate_dropdown(self):
        """Populate the UI dropdown with discovered dock devices."""
        discovered = {"": "None"}
        found_macs = []

        try:
            import dbus

            bus = dbus.SystemBus()
            om = dbus.Interface(
                bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
            )
            objects = om.GetManagedObjects()
            for path, ifaces in objects.items():
                props = ifaces.get("org.bluez.Device1")
                if not props:
                    continue
                name = str(props.get("Name", props.get("Alias", "")))
                mac = str(props.get("Address", "")).upper()
                if "Cooling" in name:
                    discovered[mac] = f"{name} ({mac})"
                    found_macs.append(mac)
        except Exception as e:
            logger.debug(f"D-Bus dropdown populate failed: {e}")

        try:
            devices = await BleakScanner.discover(timeout=3)
            for d in devices:
                if d.name and "Cooling" in d.name:
                    discovered[d.address.upper()] = f"{d.name} ({d.address.upper()})"
                    found_macs.append(d.address.upper())
        except Exception:
            pass

        with self.conf_lock:
            old_keys = set(self._discovered_macs.keys())
            new_keys = set(discovered.keys())
            self._discovered_macs = discovered


            if self._mac_address == "" and found_macs:
                self._mac_address = found_macs[0]
                if self.conf is not None:
                    self.conf["cooling_dock.dock.mac_address"] = found_macs[0]

            if old_keys != new_keys and self.emit:
                self.emit({"type": "settings"})

    def _remove_stale_bond(self, mac: str):
        """Remove BlueZ bond. The dock's HID profile triggers SMP pairing with
        random addresses, so bonds go stale quickly and block reconnection."""
        if not mac:
            return

        try:
            import dbus

            bus = dbus.SystemBus()
            obj = bus.get_object("org.bluez", "/")
            om = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            for path, ifaces in sorted(objects.items()):
                props = ifaces.get("org.bluez.Device1")
                if not props:
                    continue
                if str(props.get("Address", "")).upper() != mac.upper():
                    continue
                logger.info(f"Removing stale BlueZ bond for {mac}")
                adapter = dbus.Interface(
                    bus.get_object("org.bluez", str(path).rsplit("/", 1)[0]),
                    "org.bluez.Adapter1",
                )
                adapter.RemoveDevice(dbus.ObjectPath(path))
                import time

                time.sleep(0.5)
                return
        except ImportError:
            pass  # python-dbus not installed, fall through
        except Exception as e:
            logger.debug(f"BlueZ D-Bus bond removal failed: {e}")


        try:
            import subprocess

            subprocess.run(
                ["bluetoothctl", "remove", mac],
                capture_output=True,
                text=True,
                timeout=3,
            )
            logger.info(f"Removed stale bond for {mac} via bluetoothctl")
        except Exception as e:
            logger.debug(f"bluetoothctl remove failed: {e}")

    def _forget_bluez_device(self):
        """Remove the dock from BlueZ entirely so it stops auto-connecting."""
        mac = self._mac_address
        if not mac:
            return
        try:
            import dbus

            bus = dbus.SystemBus()
            obj = bus.get_object("org.bluez", "/")
            om = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            for path, ifaces in sorted(objects.items()):
                props = ifaces.get("org.bluez.Device1")
                if not props:
                    continue
                if str(props.get("Address", "")).upper() != mac.upper():
                    continue
                logger.info(f"Removing Cooling Dock {mac} from BlueZ")
                adapter = dbus.Interface(
                    bus.get_object("org.bluez", str(path).rsplit("/", 1)[0]),
                    "org.bluez.Adapter1",
                )
                adapter.RemoveDevice(dbus.ObjectPath(path))
                return
        except Exception as e:
            logger.debug(f"BlueZ forget failed: {e}")

    def _find_connected_dock_via_bluez(
        self, target_mac: str | None = None
    ) -> BLEDevice | None:
        """Find a dock already connected to BlueZ (not advertising)."""
        try:
            import dbus

            bus = dbus.SystemBus()
            obj = bus.get_object("org.bluez", "/")
            om = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            for path, ifaces in sorted(objects.items()):
                props = ifaces.get("org.bluez.Device1")
                if not props:
                    continue
                if not bool(props.get("Connected", False)):
                    continue
                name = str(props.get("Name", ""))
                if "Cooling" not in name:
                    continue
                mac = str(props.get("Address", "")).upper()
                if target_mac and mac != target_mac:
                    continue
                logger.info(f"Found connected Cooling Dock at {mac}")
                return BLEDevice(mac, name, {"path": str(path)})
        except Exception as e:
            logger.debug(f"BlueZ D-Bus connected-dock check failed: {e}")


        try:
            import subprocess

            result = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in result.stdout.split("\n"):
                if "CoolingSystem" not in line and "Cooling" not in line:
                    continue
                parts = line.strip().split(" ", 2)
                if len(parts) < 3:
                    continue
                mac = parts[1].upper()
                if target_mac and mac != target_mac:
                    continue
                info = subprocess.run(
                    ["bluetoothctl", "info", mac],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if "Connected: yes" in info.stdout:
                    logger.info(f"Found connected Cooling Dock at {mac}")
                    path = f"/org/bluez/hci0/dev_{mac.replace(':', '_')}"
                    return BLEDevice(mac, parts[2], {"path": path})
        except Exception as e:
            logger.debug(f"BlueZ connected-dock check failed: {e}")
        return None


def _is_supported_device() -> bool:
    try:
        with open("/sys/devices/virtual/dmi/id/product_name") as f:
            prod = f.read().strip()
        return prod in SUPPORTED_PRODUCTS
    except Exception:
        return False


def autodetect(existing: Sequence[HHDPlugin]) -> Sequence[HHDPlugin]:
    if len([p for p in existing if p.name == "cooling_dock"]):
        return existing

    if not _is_supported_device():
        return existing

    return [CoolingDockPlugin()]
