import ctypes
import errno
import fcntl
import logging
import os
import platform
import select
import socket
import time
from dataclasses import dataclass

from hhd.controller.lib.ioctl import _IOR, _IOW, _IOWR

logger = logging.getLogger(__name__)

CEC_MAX_LOG_ADDRS = 4
CEC_MAX_MSG_SIZE = 16


class CecCaps(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_char * 32),
        ("name", ctypes.c_char * 32),
        ("available_log_addrs", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
    ]


class CecLogAddrs(ctypes.Structure):
    _fields_ = [
        ("log_addr", ctypes.c_uint8 * CEC_MAX_LOG_ADDRS),
        ("log_addr_mask", ctypes.c_uint16),
        ("cec_version", ctypes.c_uint8),
        ("num_log_addrs", ctypes.c_uint8),
        ("vendor_id", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("osd_name", ctypes.c_char * 15),
        ("primary_device_type", ctypes.c_uint8 * CEC_MAX_LOG_ADDRS),
        ("log_addr_type", ctypes.c_uint8 * CEC_MAX_LOG_ADDRS),
        ("all_device_types", ctypes.c_uint8 * CEC_MAX_LOG_ADDRS),
        ("features", (ctypes.c_uint8 * 12) * CEC_MAX_LOG_ADDRS),
    ]


class CecMsg(ctypes.Structure):
    _fields_ = [
        ("tx_ts", ctypes.c_uint64),
        ("rx_ts", ctypes.c_uint64),
        ("len", ctypes.c_uint32),
        ("timeout", ctypes.c_uint32),
        ("sequence", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("msg", ctypes.c_uint8 * CEC_MAX_MSG_SIZE),
        ("reply", ctypes.c_uint8),
        ("rx_status", ctypes.c_uint8),
        ("tx_status", ctypes.c_uint8),
        ("tx_arb_lost_cnt", ctypes.c_uint8),
        ("tx_nack_cnt", ctypes.c_uint8),
        ("tx_low_drive_cnt", ctypes.c_uint8),
        ("tx_error_cnt", ctypes.c_uint8),
    ]


CEC_ADAP_G_CAPS = _IOWR("a", 0, ctypes.sizeof(CecCaps))
CEC_ADAP_G_PHYS_ADDR = _IOR("a", 1, ctypes.sizeof(ctypes.c_uint16))
CEC_ADAP_S_LOG_ADDRS = _IOWR("a", 4, ctypes.sizeof(CecLogAddrs))
CEC_TRANSMIT = _IOWR("a", 5, ctypes.sizeof(CecMsg))
CEC_RECEIVE = _IOWR("a", 6, ctypes.sizeof(CecMsg))
CEC_S_MODE = _IOW("a", 9, ctypes.sizeof(ctypes.c_uint32))

CEC_CAP_LOG_ADDRS = 1 << 1
CEC_CAP_TRANSMIT = 1 << 2
CEC_PHYS_ADDR_INVALID = 0xFFFF
CEC_LOG_ADDR_INVALID = 0xFF
CEC_MODE_INITIATOR = 1
CEC_MODE_FOLLOWER = 1 << 4
CEC_OP_CEC_VERSION_2_0 = 6
CEC_VENDOR_ID_NONE = 0xFFFFFFFF
CEC_OP_PRIM_DEVTYPE_PLAYBACK = 4
CEC_LOG_ADDR_TYPE_PLAYBACK = 3
CEC_OP_ALL_DEVTYPE_PLAYBACK = 0x10

CEC_LOG_ADDR_TV = 0
CEC_LOG_ADDR_BROADCAST = 15

CEC_TX_STATUS_OK = 1 << 0
CEC_RX_STATUS_OK = 1 << 0

CEC_MSG_ACTIVE_SOURCE = 0x82
CEC_MSG_IMAGE_VIEW_ON = 0x04
CEC_MSG_INACTIVE_SOURCE = 0x9D
CEC_MSG_REQUEST_ACTIVE_SOURCE = 0x85
CEC_MSG_REPORT_PHYSICAL_ADDR = 0x84
CEC_MSG_SET_OSD_NAME = 0x47
CEC_MSG_STANDBY = 0x36
CEC_MSG_GIVE_DEVICE_POWER_STATUS = 0x8F
CEC_MSG_REPORT_POWER_STATUS = 0x90
CEC_MSG_USER_CONTROL_PRESSED = 0x44
CEC_MSG_USER_CONTROL_RELEASED = 0x45

CEC_OP_POWER_STATUS_STANDBY = 1
CEC_OP_UI_CMD_SELECT = 0x00
CEC_OP_UI_CMD_UP = 0x01
CEC_OP_UI_CMD_DOWN = 0x02
CEC_OP_UI_CMD_LEFT = 0x03
CEC_OP_UI_CMD_RIGHT = 0x04
CEC_OP_UI_CMD_BACK = 0x0D
CEC_OP_UI_CMD_ENTER = 0x2B


def _ioctl(fd: int, request: int, value: ctypes.Structure | ctypes._SimpleCData):
    size = ctypes.sizeof(value)
    data = bytearray(ctypes.string_at(ctypes.addressof(value), size))
    fcntl.ioctl(fd, request, data, True)
    ctypes.memmove(ctypes.addressof(value), bytes(data), size)
    return value


def _get_osd_name() -> bytes:
    try:
        name = platform.freedesktop_os_release().get("PRETTY_NAME", "").strip()
    except Exception:
        name = ""
    if not name:
        name = socket.gethostname().strip()
    if not name:
        name = "HHD"

    encoded = name.encode("utf-8")[:14]
    while encoded:
        try:
            encoded.decode("utf-8")
            break
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return encoded


@dataclass
class CecState:
    dev: str
    fd: int
    phys_addr: int
    logical_addr: int
    osd_name: bytes
    powered_by_hhd: bool = False
    announced_active: bool = False
    active: bool = False
    closed: bool = False


def receive_cec(state: CecState, timeout: int = 0) -> CecMsg | None:
    try:
        readable, _, _ = select.select([state.fd], [], [], timeout / 1000)
    except InterruptedError:
        return None
    if not readable:
        return None

    msg = CecMsg()
    try:
        _ioctl(state.fd, CEC_RECEIVE, msg)
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.ETIMEDOUT):
            return None
        raise
    if not msg.rx_status & CEC_RX_STATUS_OK or msg.len < 2:
        return None
    return msg


def _transmit(
    state: CecState,
    destination: int,
    opcode: int,
    operands: tuple[int, ...] = (),
    reply: int = 0,
    timeout: int = 1000,
) -> CecMsg | None:
    broadcast_reply = bool(reply and destination == CEC_LOG_ADDR_BROADCAST)
    msg = CecMsg()
    msg.len = 2 + len(operands)
    msg.timeout = timeout
    msg.msg[0] = (state.logical_addr << 4) | destination
    msg.msg[1] = opcode
    for idx, operand in enumerate(operands, start=2):
        msg.msg[idx] = operand
    msg.reply = 0 if broadcast_reply else reply

    _ioctl(state.fd, CEC_TRANSMIT, msg)
    if not msg.tx_status & CEC_TX_STATUS_OK:
        return None
    if broadcast_reply:
        deadline = time.monotonic() + timeout / 1000
        while (remaining := deadline - time.monotonic()) > 0:
            received = receive_cec(state, max(1, int(remaining * 1000)))
            if received is None:
                return None
            if received.msg[1] == reply:
                return received
        return None
    if reply and (
        not msg.rx_status & CEC_RX_STATUS_OK or msg.len < 2 or msg.msg[1] != reply
    ):
        return None
    return msg


def initialize_cec(dev: str) -> CecState:
    fd = os.open(dev, os.O_RDWR | os.O_CLOEXEC)
    try:
        caps = _ioctl(fd, CEC_ADAP_G_CAPS, CecCaps())
        required = CEC_CAP_LOG_ADDRS | CEC_CAP_TRANSMIT
        if caps.capabilities & required != required:
            raise OSError(f"CEC adapter lacks required capabilities: {dev}")
        if caps.available_log_addrs < 1:
            raise OSError(f"CEC adapter has no available logical addresses: {dev}")

        _ioctl(
            fd,
            CEC_S_MODE,
            ctypes.c_uint32(CEC_MODE_INITIATOR | CEC_MODE_FOLLOWER),
        )

        phys_addr = ctypes.c_uint16()
        _ioctl(fd, CEC_ADAP_G_PHYS_ADDR, phys_addr)
        if phys_addr.value == CEC_PHYS_ADDR_INVALID:
            raise OSError(f"CEC adapter is not connected: {dev}")

        claimed_name = _get_osd_name()
        laddrs = CecLogAddrs()
        laddrs.cec_version = CEC_OP_CEC_VERSION_2_0
        laddrs.num_log_addrs = 1
        laddrs.vendor_id = CEC_VENDOR_ID_NONE
        laddrs.osd_name = claimed_name
        laddrs.primary_device_type[0] = CEC_OP_PRIM_DEVTYPE_PLAYBACK
        laddrs.log_addr_type[0] = CEC_LOG_ADDR_TYPE_PLAYBACK
        laddrs.all_device_types[0] = CEC_OP_ALL_DEVTYPE_PLAYBACK
        _ioctl(fd, CEC_ADAP_S_LOG_ADDRS, laddrs)

        logical_addr = int(laddrs.log_addr[0])
        if (
            logical_addr == CEC_LOG_ADDR_INVALID
            or logical_addr == CEC_LOG_ADDR_BROADCAST
            or not laddrs.log_addr_mask & (1 << logical_addr)
        ):
            raise OSError(f"Could not claim a playback address on {dev}")
    except Exception:
        os.close(fd)
        raise

    state = CecState(dev, fd, phys_addr.value, logical_addr, claimed_name)

    try:
        msg = _transmit(
            state,
            CEC_LOG_ADDR_TV,
            CEC_MSG_GIVE_DEVICE_POWER_STATUS,
            reply=CEC_MSG_REPORT_POWER_STATUS,
        )
        power = int(msg.msg[2]) if msg and msg.len >= 3 else None
    except OSError as e:
        logger.warning(f"Could not query TV power through {dev}: {e}")
        power = None

    if power == CEC_OP_POWER_STATUS_STANDBY:
        try:
            state.powered_by_hhd = (
                _transmit(state, CEC_LOG_ADDR_TV, CEC_MSG_IMAGE_VIEW_ON) is not None
            )
        except OSError as e:
            logger.warning(f"Could not turn on TV through {dev}: {e}")

    try:
        _transmit(
            state,
            CEC_LOG_ADDR_BROADCAST,
            CEC_MSG_REPORT_PHYSICAL_ADDR,
            (
                state.phys_addr >> 8,
                state.phys_addr & 0xFF,
                CEC_OP_PRIM_DEVTYPE_PLAYBACK,
            ),
        )
        _transmit(state, CEC_LOG_ADDR_TV, CEC_MSG_SET_OSD_NAME, tuple(state.osd_name))
    except OSError as e:
        logger.warning(f"Could not identify CEC source through {dev}: {e}")

    try:
        msg = _transmit(
            state,
            CEC_LOG_ADDR_BROADCAST,
            CEC_MSG_REQUEST_ACTIVE_SOURCE,
            reply=CEC_MSG_ACTIVE_SOURCE,
        )
        active = (
            (int(msg.msg[2]) << 8) | int(msg.msg[3]) if msg and msg.len >= 4 else None
        )
    except OSError as e:
        logger.warning(f"Could not query active CEC source through {dev}: {e}")
        active = None

    if active != state.phys_addr:
        try:
            state.announced_active = (
                _transmit(
                    state,
                    CEC_LOG_ADDR_BROADCAST,
                    CEC_MSG_ACTIVE_SOURCE,
                    (state.phys_addr >> 8, state.phys_addr & 0xFF),
                )
                is not None
            )
            state.active = state.announced_active
        except OSError as e:
            logger.warning(f"Could not announce active CEC source through {dev}: {e}")
    else:
        state.active = True

    return state


def uninitialize(state: CecState):
    if state.closed:
        return
    state.closed = True
    try:
        active = state.active
        if state.powered_by_hhd:
            try:
                msg = _transmit(
                    state,
                    CEC_LOG_ADDR_BROADCAST,
                    CEC_MSG_REQUEST_ACTIVE_SOURCE,
                    reply=CEC_MSG_ACTIVE_SOURCE,
                )
                if msg and msg.len >= 4:
                    active = (
                        (int(msg.msg[2]) << 8) | int(msg.msg[3])
                    ) == state.phys_addr
            except OSError as e:
                logger.warning(
                    f"Could not verify active CEC source through {state.dev}: {e}"
                )

        # Image View On can select our input even if Active Source failed or
        # the TV already considered this address active. Announce inactivity
        # before undoing a power-on in either case.
        if state.announced_active or state.powered_by_hhd:
            try:
                _transmit(
                    state,
                    CEC_LOG_ADDR_TV,
                    CEC_MSG_INACTIVE_SOURCE,
                    (state.phys_addr >> 8, state.phys_addr & 0xFF),
                )
            except OSError as e:
                logger.warning(
                    f"Could not announce inactive CEC source through {state.dev}: {e}"
                )
        if state.powered_by_hhd and active:
            try:
                _transmit(state, CEC_LOG_ADDR_TV, CEC_MSG_STANDBY)
            except OSError as e:
                logger.warning(f"Could not put TV in standby through {state.dev}: {e}")
        elif state.powered_by_hhd:
            logger.info(
                f"Leaving TV on because {state.dev} is not confirmed as active."
            )
    finally:
        try:
            _ioctl(state.fd, CEC_ADAP_S_LOG_ADDRS, CecLogAddrs())
        except OSError:
            pass
        os.close(state.fd)
