# SPDX-License-Identifier: MIT
# Taken from unmaintained library python-uhid

from __future__ import annotations

import asyncio
import ctypes
import enum
import fcntl
import functools
import inspect
import logging
import os
import os.path
import select
import struct
import time
import typing
import uuid

from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Type, Union


if typing.TYPE_CHECKING:
    import threading  # pragma: no cover

    import trio  # pragma: no cover


__version__ = "0.0.1"


_HID_MAX_DESCRIPTOR_SIZE = 4096
_UHID_DATA_MAX = 4096


class Bus(enum.Enum):
    PCI = 0x01
    ISAPNP = 0x02
    USB = 0x03
    HIL = 0x04
    BLUETOOTH = 0x05
    VIRTUAL = 0x06


class _EventType(enum.Enum):
    # UHID_LEGACY_CREATE = 0
    UHID_DESTROY = 1
    UHID_START = 2
    UHID_STOP = 3
    UHID_OPEN = 4
    UHID_CLOSE = 5
    UHID_OUTPUT = 6
    # UHID_LEGACY_OUTPUT_EV = 7
    # UHID_LEGACY_INPUT = 8
    UHID_GET_REPORT = 9
    UHID_GET_REPORT_REPLY = 10
    UHID_CREATE2 = 11
    UHID_INPUT2 = 12
    UHID_SET_REPORT = 13
    UHID_SET_REPORT_REPLY = 14


class _DevFlag(enum.Enum):
    UHID_DEV_NUMBERED_FEATURE_REPORTS = 1 << 0
    UHID_DEV_NUMBERED_OUTPUT_REPORTS = 1 << 1
    UHID_DEV_NUMBERED_INPUT_REPORTS = 1 << 2


class _ReportType(enum.Enum):
    UHID_FEATURE_REPORT = 0
    UHID_OUTPUT_REPORT = 1
    UHID_INPUT_REPORT = 2


# _LegacyEventType


class _Create2Req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("name", ctypes.c_char * 128),
        ("phys", ctypes.c_char * 64),
        ("uniq", ctypes.c_char * 64),
        ("rd_size", ctypes.c_uint16),
        ("bus", ctypes.c_uint16),
        ("vendor", ctypes.c_uint32),
        ("product", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("country", ctypes.c_uint32),
        ("rd_data", ctypes.c_uint8 * _HID_MAX_DESCRIPTOR_SIZE),
    ]


class _StartReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dev_flags", ctypes.c_uint64),
    ]


class _Input2Req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * _UHID_DATA_MAX),
    ]


class _OutputReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("data", ctypes.c_uint8 * _UHID_DATA_MAX),
        ("size", ctypes.c_uint16),
        ("rtype", ctypes.c_uint8),
    ]


class _GetReportReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("rnum", ctypes.c_uint8),
        ("rtype", ctypes.c_uint8),
    ]


class _GetReportReplyReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("err", ctypes.c_uint16),
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * _UHID_DATA_MAX),
    ]


class _SetReportReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint64),
        ("rnum", ctypes.c_uint8),
        ("rtype", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * _UHID_DATA_MAX),
    ]


class _SetReportReplyReq(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("err", ctypes.c_uint16),
    ]


class _U(ctypes.Union):
    _fields_ = [
        ("output", _OutputReq),
        ("get_report", _GetReportReq),
        ("get_report_reply", _GetReportReplyReq),
        ("create2", _Create2Req),
        ("input2", _Input2Req),
        ("set_report", _SetReportReq),
        ("set_report_reply", _SetReportReplyReq),
        ("start", _StartReq),
    ]


class _Event(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("u", _U),
    ]


class UHIDException(Exception):
    """
    Exception triggered when interfacing with UHID
    """


class _UHIDBase(object):
    """
    UHID interface implementation base

    Does not do IO, only constructs the events.
    """

    def __init__(self) -> None:
        if not os.path.exists("/dev/uhid"):  # pragma: no cover
            raise RuntimeError("UHID is not available (/dev/uhid is missing)")

        self.__logger = logging.getLogger(self.__class__.__name__)
        self._created = False
        self._started = False
        self._open_count = 0
        self._construct_event: Dict[_EventType, Callable[..., bytes]] = {
            _EventType.UHID_CREATE2: self._create_event,
            _EventType.UHID_DESTROY: self._destroy_event,
            _EventType.UHID_INPUT2: self._input2_event,
        }

        self.receive_start: Optional[Callable[[int], None]] = None
        self.receive_open: Optional[Callable[[], None]] = None
        self.receive_close: Optional[Callable[[], None]] = None
        self.receive_output: Optional[
            Callable[[List[int], _ReportType], Optional[Awaitable[None]]]
        ] = None

    def _receive_dispatch(
        self, buffer: bytes
    ) -> Optional[Callable[[], Optional[Awaitable[None]]]]:
        event_type = struct.unpack_from("< L", buffer)[0]

        if event_type == _EventType.UHID_START.value:
            _, dev_flags = struct.unpack_from("< L Q", buffer)
            self.__logger.debug("device started")
            self._started = True
            if self.receive_start:
                return functools.partial(self.receive_start, dev_flags)

        elif event_type == _EventType.UHID_OPEN.value:
            self._open_count += 1
            self.__logger.debug(
                f"device was opened (it now has {self._open_count} open instances)"
            )
            if self.receive_open:
                return functools.partial(self.receive_open)

        elif event_type == _EventType.UHID_CLOSE.value:
            self._open_count -= 1
            self.__logger.debug(
                f"device was closed (it now has {self._open_count} open instances)"
            )
            if self.receive_close:
                return functools.partial(self.receive_close)

        elif event_type == _EventType.UHID_OUTPUT.value:
            if self.receive_output:
                _, data, size, rtype = struct.unpack_from("< L 4096s H B", buffer)
                return functools.partial(
                    self.receive_output,
                    list(data)[:size],
                    _ReportType(rtype),
                )
        # TODO: stop, get_report, set_report
        return None

    def _create_event(
        self,
        name: str,
        phys: str,
        uniq: str,
        bus: int,
        vendor: int,
        product: int,
        version: int,
        country: int,
        rd_data: Sequence[int],
    ) -> bytes:
        if self._created:
            raise UHIDException(
                "This instance already has a device open, it is only possible to open 1 device per instance"
            )
        self._created = True

        if len(name) > _Create2Req.name.size:
            raise UHIDException(
                f"UHID_CREATE2: name is too big ({len(name) > _Create2Req.name.size})"
            )

        if len(phys) > _Create2Req.phys.size:
            raise UHIDException(
                f"UHID_CREATE2: phys is too big ({len(phys) > _Create2Req.phys.size})"
            )

        if len(uniq) > _Create2Req.uniq.size:
            raise UHIDException(
                f"UHID_CREATE2: uniq is too big ({len(uniq) > _Create2Req.uniq.size})"
            )

        if len(rd_data) > _Create2Req.rd_data.size:
            raise UHIDException(
                f"UHID_CREATE2: rd_data is too big ({len(rd_data) > _Create2Req.rd_data.size})"
            )

        return struct.pack(
            "< L 128s 64s 64s H H L L L L 4096s",
            _EventType.UHID_CREATE2.value,
            name.encode(),
            phys.encode(),
            uniq.encode(),
            len(rd_data),
            bus,
            vendor,
            product,
            version,
            country,
            bytes(rd_data),
        )

    def _destroy_event(self) -> bytes:
        self._created = False
        return struct.pack("< L", _EventType.UHID_DESTROY.value)

    def _input2_event(self, data: Sequence[int]) -> bytes:
        if len(data) > _Input2Req.data.size:
            raise UHIDException(
                f"UHID_INPUT2: data is too big ({len(data) > _Input2Req.data.size})"
            )

        return struct.pack(
            "< L H 4096s",
            _EventType.UHID_INPUT2.value,
            len(data),
            bytes(data),
        )

    # TODO: get_report_reply, set_report_reply

    @property
    def started(self) -> bool:
        return self._started


class _BlockingUHIDBase(_UHIDBase):
    """
    Base for blocking IO based UHID interface implementation
    """

    def __init__(self) -> None:
        super().__init__()
        self.__logger = logging.getLogger(self.__class__.__name__)

        self._uhid = os.open("/dev/uhid", os.O_RDWR)

    def _write(self, event: bytes) -> None:
        n = os.write(self._uhid, bytearray(event))
        if n != len(event):  # pragma: no cover
            raise UHIDException(f"Failed to send data ({n} != {len(event)})")

    def _read(self) -> None:
        callback = self._receive_dispatch(os.read(self._uhid, ctypes.sizeof(_Event)))
        if callback:
            if inspect.iscoroutinefunction(callback):
                raise TypeError(
                    f"{self.__class__.__name__} does not support async callbacks (got {callback})"
                )
            callback()

    def _send_event(self, event: bytes) -> None:
        self._write(event)

    def send_event(self, event_type: _EventType, *args: Any, **kwargs: Any) -> None:
        self._send_event(self._construct_event[event_type](*args, **kwargs))


class PolledBlockingUHID(_BlockingUHIDBase):
    """
    Blocking IO UHID implementation using epoll
    """

    def single_dispatch(self) -> None:
        self._read()

    def dispatch(self, stop: Optional[threading.Event] = None) -> None:
        poller = select.epoll()
        poller.register(self._uhid, select.EPOLLIN)
        while not stop.is_set() if stop else True:
            for _fd, _event_type in poller.poll():
                self.single_dispatch()


class AsyncioBlockingUHID(_BlockingUHIDBase):
    """
    Blocking IO UHID implementation using AsyncIO readers and writers

    AsyncIO will watch the UHID file descriptor and schedule read and write
    tasks when it is ready for those operations.
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        super().__init__()
        self._loop = loop if loop else asyncio.get_event_loop()

        fcntl.fcntl(self._uhid, fcntl.F_SETFL, os.O_NONBLOCK)

        self._write_queue: List[bytes] = []

        self._writer_registered = False
        self._loop.add_reader(self._uhid, self._read)

    def _async_writer(self) -> None:
        self._write(self._write_queue.pop(0))
        if not self._write_queue:
            self._loop.remove_writer(self._uhid)
            self._writer_registered = False

    def _send_event(self, event: bytes) -> None:
        # TODO: benchmark loop.add_writer vs plain write, I feel plain write should be faster in the UHID fd
        self._write_queue.append(event)
        if self._write_queue and not self._writer_registered:
            self._loop.add_writer(self._uhid, self._async_writer)
            self._writer_registered = True


class TrioUHID(_UHIDBase):
    """
    Trio UHID implementation
    """

    def __init__(self, file) -> None:
        super().__init__()
        self.__logger = logging.getLogger(self.__class__.__name__)
        self._uhid = file

    @classmethod
    async def new(cls) -> TrioUHID:
        """
        Async initializer
        """
        import trio

        return cls(await trio.open_file("/dev/uhid", "rb+", buffering=0))

    async def _write(self, event: bytes) -> None:
        await self._uhid.write(event)

    async def single_dispatch(self) -> None:
        callback = self._receive_dispatch(await self._uhid.read(ctypes.sizeof(_Event)))
        if callback:
            if inspect.iscoroutinefunction(callback):
                async_callback = typing.cast(Callable[[], Awaitable[None]], callback)
                await async_callback()
            else:
                callback()

    async def dispatch(self) -> None:
        while True:
            await self.single_dispatch()

    async def send_event(
        self, event_type: _EventType, *args: Any, **kwargs: Any
    ) -> None:
        await self._write(self._construct_event[event_type](*args, **kwargs))


class _UHIDDeviceBase(object):
    def __init__(
        self,
        uhid_backend: _UHIDBase,
        vid: int,
        pid: int,
        name: str,
        report_descriptor: Sequence[int],
        bus: Bus = Bus.USB,
        physical_name: Optional[str] = None,
        unique_name: Optional[str] = None,
        version: int = 0,
        country: int = 0,
    ) -> None:
        if not unique_name:
            unique_name = f"{self.__class__.__name__}_{uuid.uuid4()}"[:63]

        if not physical_name:
            physical_name = f"{self.__class__.__name__}/{unique_name}"[:63]

        self._bus = bus
        self._vid = vid
        self._pid = pid
        self._name = name
        self._phys = physical_name
        self._uniq = unique_name
        self._version = version
        self._country = country
        self._rdesc = report_descriptor

        self.__logger = logging.getLogger(self.__class__.__name__)

        self._backend = uhid_backend

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(vid={self.vid}, pid={self.pid}, name={self.name}, uniq={self.unique_name})"

    @property
    def bus(self) -> Bus:
        return self._bus

    @property
    def vid(self) -> int:
        return self._vid

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def name(self) -> str:
        return self._name

    @property
    def physical_name(self) -> str:
        return self._phys

    @property
    def unique_name(self) -> str:
        return self._uniq

    @property
    def report_descriptor(self) -> Sequence[int]:
        # lists are mutable, we don't want users to modify our private list :)
        if isinstance(self._rdesc, list):
            return self._rdesc.copy()
        return self._rdesc

    @property
    def version(self) -> int:
        return self._version

    @property
    def country(self) -> int:
        return self._country

    # callbacks

    @property
    def receive_start(self) -> Optional[Callable[[int], None]]:
        return self._backend.receive_start

    @receive_start.setter
    def receive_start(self, callback: Optional[Callable[[int], None]]) -> None:
        self._backend.receive_start = callback

    @property
    def receive_open(self) -> Optional[Callable[[], None]]:
        return self._backend.receive_open

    @receive_open.setter
    def receive_open(self, callback: Optional[Callable[[], None]]) -> None:
        self._backend.receive_open = callback

    @property
    def receive_close(self) -> Optional[Callable[[], None]]:
        return self._backend.receive_close

    @receive_close.setter
    def receive_close(self, callback: Optional[Callable[[], None]]) -> None:
        self._backend.receive_close = callback

    @property
    def receive_output(
        self,
    ) -> Optional[Callable[[List[int], _ReportType], Optional[Awaitable[None]]]]:
        return self._backend.receive_output

    @receive_output.setter
    def receive_output(
        self,
        callback: Optional[
            Callable[[List[int], _ReportType], Optional[Awaitable[None]]]
        ],
    ) -> None:
        self._backend.receive_output = callback


class UHIDDevice(_UHIDDeviceBase):
    """
    UHID device
    """

    def __init__(
        self,
        vid: int,
        pid: int,
        name: str,
        report_descriptor: Sequence[int],
        *,
        bus: Bus = Bus.USB,
        physical_name: Optional[str] = None,
        unique_name: Optional[str] = None,
        version: int = 0,
        country: int = 0,
        backend: Type[
            Union[PolledBlockingUHID, AsyncioBlockingUHID]
        ] = PolledBlockingUHID,
    ) -> None:
        uhid = backend()
        super().__init__(
            uhid,
            vid,
            pid,
            name,
            report_descriptor,
            bus,
            physical_name,
            unique_name,
            version,
            country,
        )
        self.__logger = logging.getLogger(self.__class__.__name__)

        self._uhid = uhid
        self.initialize()

    def initialize(self) -> None:
        """
        Initializes the device

        Subclasses can overwrite this method. There are several use cases for that,
        eg. delay initialization, custom initialization, etc.
        """
        self.__logger.info("initializing device")
        self._create()

    def _create(self) -> None:
        self.__logger.info(f"(UHID_CREATE2) create {self}")
        self._uhid.send_event(
            _EventType.UHID_CREATE2,
            self._name,
            self._phys,
            self._uniq,
            self._bus.value,
            self._vid,
            self._pid,
            self._version,
            self._country,
            self._rdesc,
        )

    def wait_for_start(self, delay: float = 0.05) -> None:
        while not self._uhid.started:
            self.single_dispatch()
            time.sleep(delay)

    async def wait_for_start_asyncio(self, delay: float = 0.05) -> None:
        while not self._uhid.started:
            self.single_dispatch()
            await asyncio.sleep(delay)

    def dispatch(self, stop: Optional[threading.Event] = None) -> None:
        if isinstance(self._uhid, PolledBlockingUHID):
            self._uhid.dispatch(stop)

    def single_dispatch(self) -> None:
        if isinstance(self._uhid, PolledBlockingUHID):
            self._uhid.single_dispatch()

    def destroy(self) -> None:
        self.__logger.info(f"(UHID_DESTROY) destroy {self}")
        self._uhid.send_event(_EventType.UHID_DESTROY)

    def send_input(self, data: Sequence[int]) -> None:
        if self.__logger.level <= logging.INFO:
            self.__logger.info(
                "(UHID_INPUT2) send {}".format(
                    "".join([f"{byte:02x}" for byte in data])
                )
            )
        self._uhid.send_event(_EventType.UHID_INPUT2, data)


class AsyncUHIDDevice(_UHIDDeviceBase):
    """
    UHID device with an async API
    """

    def __init__(
        self,
        backend: TrioUHID,
        vid: int,
        pid: int,
        name: str,
        report_descriptor: Sequence[int],
        bus: Bus = Bus.USB,
        physical_name: Optional[str] = None,
        unique_name: Optional[str] = None,
        version: int = 0,
        country: int = 0,
    ) -> None:
        super().__init__(
            backend,
            vid,
            pid,
            name,
            report_descriptor,
            bus,
            physical_name,
            unique_name,
            version,
            country,
        )
        self.__logger = logging.getLogger(self.__class__.__name__)
        self._uhid = backend

    @classmethod
    async def new(
        cls,
        vid: int,
        pid: int,
        name: str,
        report_descriptor: Sequence[int],
        *,
        bus: Bus = Bus.USB,
        physical_name: Optional[str] = None,
        unique_name: Optional[str] = None,
        version: int = 0,
        country: int = 0,
        backend: Type[TrioUHID],
    ) -> AsyncUHIDDevice:
        device = cls(
            await backend.new(),
            vid,
            pid,
            name,
            report_descriptor,
            bus,
            physical_name,
            unique_name,
            version,
            country,
        )
        await device.initialize()
        return device

    async def initialize(self) -> None:
        """
        Initializes the device

        Subclasses can overwrite this method. There are several use cases for that,
        eg. delay initialization, custom initialization, etc.
        """
        self.__logger.info("initializing device")
        await self._create()

    async def wait_for_start(self, delay: float = 0.05) -> None:
        while not self._uhid.started:
            await self.single_dispatch()

    async def dispatch(self) -> None:
        await self._uhid.dispatch()

    async def single_dispatch(self) -> None:
        await self._uhid.single_dispatch()

    async def _create(self) -> None:
        self.__logger.info(f"(UHID_CREATE2) create {self}")
        await self._uhid.send_event(
            _EventType.UHID_CREATE2,
            self._name,
            self._phys,
            self._uniq,
            self._bus.value,
            self._vid,
            self._pid,
            self._version,
            self._country,
            self._rdesc,
        )

    async def destroy(self) -> None:
        self.__logger.info(f"(UHID_DESTROY) destroy {self}")
        await self._uhid.send_event(_EventType.UHID_DESTROY)

    async def send_input(self, data: Sequence[int]) -> None:
        if self.__logger.level <= logging.INFO:
            self.__logger.info(
                "(UHID_INPUT2) send {}".format(
                    "".join([f"{byte:02x}" for byte in data])
                )
            )
        await self._uhid.send_event(_EventType.UHID_INPUT2, data)
