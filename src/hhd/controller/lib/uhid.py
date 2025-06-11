# SPDX-License-Identifier: MIT and GPL-3.0-only
# Sourced from library python-uhid

from __future__ import annotations

import enum
import os
import os.path
import select
import struct
import sys
import uuid
from typing import Literal, Optional, TypedDict

from hhd.controller import can_read

# _HID_MAX_DESCRIPTOR_SIZE = 4096
UHID_DATA_MAX = 4096


BUS_PCI = 0x01
BUS_ISAPNP = 0x02
BUS_USB = 0x03
BUS_HIL = 0x04
BUS_BLUETOOTH = 0x05
BUS_VIRTUAL = 0x06


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


class DevFlag(enum.Enum):
    UHID_DEV_NUMBERED_FEATURE_REPORTS = 1 << 0
    UHID_DEV_NUMBERED_OUTPUT_REPORTS = 1 << 1
    UHID_DEV_NUMBERED_INPUT_REPORTS = 1 << 2


class ReportType(enum.Enum):
    UHID_FEATURE_REPORT = 0
    UHID_OUTPUT_REPORT = 1
    UHID_INPUT_REPORT = 2


# Used as a reference
# class Create2Req(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("name", ctypes.c_char * 128),
#         ("phys", ctypes.c_char * 64),
#         ("uniq", ctypes.c_char * 64),
#         ("rd_size", ctypes.c_uint16),
#         ("bus", ctypes.c_uint16),
#         ("vendor", ctypes.c_uint32),
#         ("product", ctypes.c_uint32),
#         ("version", ctypes.c_uint32),
#         ("country", ctypes.c_uint32),
#         ("rd_data", ctypes.c_char * _HID_MAX_DESCRIPTOR_SIZE),
#     ]


# class StartReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("dev_flags", ctypes.c_uint64),
#     ]


# class Input2Req(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("size", ctypes.c_uint16),
#         ("data", ctypes.c_char * _UHID_DATA_MAX),
#     ]


# class OutputReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("data", ctypes.c_uint8 * _UHID_DATA_MAX),
#         ("size", ctypes.c_uint16),
#         ("rtype", ctypes.c_uint8),
#     ]


# class GetReportReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("id", ctypes.c_uint32),
#         ("rnum", ctypes.c_uint8),
#         ("rtype", ctypes.c_uint8),
#     ]


# class GetReportReplyReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("id", ctypes.c_uint32),
#         ("err", ctypes.c_uint16),
#         ("size", ctypes.c_uint16),
#         ("data", ctypes.c_char * _UHID_DATA_MAX),
#     ]


# class SetReportReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("id", ctypes.c_uint64),
#         ("rnum", ctypes.c_uint8),
#         ("rtype", ctypes.c_uint8),
#         ("size", ctypes.c_uint16),
#         ("data", ctypes.c_char * _UHID_DATA_MAX),
#     ]


# class SetReportReplyReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("id", ctypes.c_uint32),
#         ("err", ctypes.c_uint16),
#     ]


# class DestroyReq(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = []


# class _U(ctypes.Union):
#     _fields_ = [
#         ("output", OutputReq),
#         ("get_report", GetReportReq),
#         ("get_report_reply", GetReportReplyReq),
#         ("create2", Create2Req),
#         ("input2", Input2Req),
#         ("set_report", SetReportReq),
#         ("set_report_reply", SetReportReplyReq),
#         ("start", StartReq),
#     ]


# class Event(ctypes.Structure):
#     _pack_ = 1
#     _fields_ = [
#         ("type", ctypes.c_uint32),
#         ("u", _U),
#     ]


class EventStart(TypedDict):
    type: Literal["start"]
    dev_flags: int


class EventOutput(TypedDict):
    type: Literal["output"]
    report: int
    data: bytes


class EventGetReport(TypedDict):
    type: Literal["get_report"]
    id: int
    rnum: int
    rtype: int


class EventSetReport(TypedDict):
    type: Literal["set_report"]
    id: int
    rnum: int
    rtype: int
    data: bytes


class EventOther(TypedDict):
    type: Literal["open", "close", "stop"]


class UhidDevice:
    def __init__(
        self,
        vid: int,
        pid: int,
        name: bytes,
        report_descriptor: bytes,
        bus: int = BUS_USB,
        physical_name: Optional[bytes] = None,
        unique_name: Optional[bytes] = None,
        version: int = 0,
        country: int = 0,
    ) -> None:
        if not unique_name:
            unique_name = f"{self.__class__.__name__}_{uuid.uuid4()}"[:63].encode()

        if not physical_name:
            physical_name = f"{self.__class__.__name__}/{unique_name}"[:63].encode()

        self.bus = bus
        self.vid = vid
        self.pid = pid
        self.name = name
        self.physical_name = physical_name
        self.unique_name = unique_name
        self.version = version
        self.country = country
        self.report_descriptor = report_descriptor

        self.fd = 0
        self.poll = None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(vid={self.vid}, pid={self.pid}, name={self.name}, uniq={self.unique_name})"

    def open(self):
        self.send_create()
        return self.fd

    def close(self):
        if self.fd:
            os.close(self.fd)
            self.fd = 0

    def send_event(self, event: bytes):
        if not self.fd:
            self.fd = os.open("/dev/uhid", os.O_RDWR)
        os.write(self.fd, event)

    def read_event(
        self,
    ) -> None | EventOther | EventStart | EventOutput | EventSetReport | EventGetReport:
        if not self.fd or not can_read(self.fd):
            return None

        # + 4 for desc, + 3 for output report
        d = os.read(self.fd, UHID_DATA_MAX + 4 + 3)

        v = int.from_bytes(d[:4], byteorder=sys.byteorder)
        if v == UHID_START:
            return {
                "type": "start",
                "dev_flags": int.from_bytes(d[4:12], byteorder=sys.byteorder),
            }
        elif v == UHID_STOP:
            return {"type": "stop"}
        elif v == UHID_OPEN:
            return {"type": "open"}
        elif v == UHID_CLOSE:
            return {"type": "close"}
        elif v == UHID_OUTPUT:
            l = int.from_bytes(d[-3:-1], byteorder=sys.byteorder)
            return {"type": "output", "report": d[-1], "data": d[4 : 4 + l]}
        elif v == UHID_SET_REPORT:
            return {
                "type": "set_report",
                "id": int.from_bytes(d[4:8], byteorder=sys.byteorder),
                "rnum": d[8],
                "rtype": d[9],
                "data": d[10:],
            }
        elif v == UHID_GET_REPORT:
            return {
                "type": "get_report",
                "id": int.from_bytes(d[4:8], byteorder=sys.byteorder),
                "rnum": d[8],
                "rtype": d[9],
            }
        assert False, f"Report type {v} uknown"

    def send_create(self) -> None:
        ev = (
            struct.pack(
                "< L 128s 64s 64s H H L L L L",
                UHID_CREATE2,
                self.name,
                self.physical_name,
                self.unique_name,
                len(self.report_descriptor),
                self.bus,
                self.vid,
                self.pid,
                self.version,
                self.country,
            )
            + self.report_descriptor
        )
        self.send_event(ev)

    def send_destroy(self) -> None:
        self.send_event(int.to_bytes(UHID_DESTROY, 4, byteorder=sys.byteorder))

    def send_input_report(self, data: bytes):
        ev = struct.pack("< L H", UHID_INPUT2, len(data)) + data
        self.send_event(ev)

    def send_get_report_reply(self, id: int, err: int, data: bytes):
        ev = struct.pack("< L L H H", UHID_GET_REPORT_REPLY, id, err, len(data)) + data
        self.send_event(ev)

    def send_set_report_reply(self, id: int, err: int):
        ev = struct.pack("< L L H", UHID_SET_REPORT_REPLY, id, err)
        self.send_event(ev)
