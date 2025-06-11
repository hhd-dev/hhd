# SPDX-License-Identifier: MIT and GPL-3.0-only
# Forked from https://github.com/apmorton/pyhidapi/blob/master/hid/__init__.py
import os
import ctypes
import atexit

__all__ = ["HIDException", "DeviceInfo", "Device", "enumerate"]


# hidapi = None
library_paths = (
    "libhidapi-hidraw.so",
    "libhidapi-hidraw.so.0",
    # Only hidraw supported due to the fd requirement
    # "libhidapi-libusb.so",
    # "libhidapi-libusb.so.0",
    # "libhidapi-iohidmanager.so",
    # "libhidapi-iohidmanager.so.0",
    # "libhidapi.dylib",
    # "hidapi.dll",
    # "libhidapi-0.dll",
)

for lib in library_paths:
    try:
        hidapi = ctypes.cdll.LoadLibrary(lib)
        break
    except OSError:
        pass
else:
    error = "Unable to load any of the following libraries:{}".format(
        " ".join(library_paths)
    )
    raise ImportError(error)


hidapi.hid_init()
atexit.register(hidapi.hid_exit)


MAX_REPORT_SIZE = 4096


class HIDException(Exception):
    pass


class DeviceInfo(ctypes.Structure):
    def as_dict(self):
        ret = {}
        for name, type in self._fields_:
            if name == "next":
                continue
            ret[name] = getattr(self, name, None)

        return ret


DeviceInfo._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(DeviceInfo)),
]


class LinuxHidDevice(ctypes.Structure):
    _fields_ = [
        ("device_handle", ctypes.c_int),
        ("blocking", ctypes.c_int),
        ("last_error_str", ctypes.c_wchar_p),
        ("hid_device_info", ctypes.c_void_p),
    ]


hidapi.hid_init.argtypes = []
hidapi.hid_init.restype = ctypes.c_int
hidapi.hid_exit.argtypes = []
hidapi.hid_exit.restype = ctypes.c_int
hidapi.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
hidapi.hid_enumerate.restype = ctypes.POINTER(DeviceInfo)
hidapi.hid_free_enumeration.argtypes = [ctypes.POINTER(DeviceInfo)]
hidapi.hid_free_enumeration.restype = None
hidapi.hid_open.argtypes = [ctypes.c_ushort, ctypes.c_ushort, ctypes.c_wchar_p]
hidapi.hid_open.restype = ctypes.POINTER(LinuxHidDevice)
hidapi.hid_open_path.argtypes = [ctypes.c_char_p]
hidapi.hid_open_path.restype = ctypes.POINTER(LinuxHidDevice)
hidapi.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
hidapi.hid_write.restype = ctypes.c_int
hidapi.hid_read_timeout.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_int,
]
hidapi.hid_read_timeout.restype = ctypes.c_int
hidapi.hid_read.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
hidapi.hid_read.restype = ctypes.c_int
hidapi.hid_get_input_report.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
]
hidapi.hid_get_input_report.restype = ctypes.c_int
hidapi.hid_set_nonblocking.argtypes = [ctypes.c_void_p, ctypes.c_int]
hidapi.hid_set_nonblocking.restype = ctypes.c_int
hidapi.hid_send_feature_report.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_int,
]
hidapi.hid_send_feature_report.restype = ctypes.c_int
hidapi.hid_get_feature_report.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_size_t,
]
hidapi.hid_get_feature_report.restype = ctypes.c_int
hidapi.hid_close.argtypes = [ctypes.c_void_p]
hidapi.hid_close.restype = None
hidapi.hid_get_manufacturer_string.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_size_t,
]
hidapi.hid_get_manufacturer_string.restype = ctypes.c_int
hidapi.hid_get_product_string.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_size_t,
]
hidapi.hid_get_product_string.restype = ctypes.c_int
hidapi.hid_get_serial_number_string.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_size_t,
]
hidapi.hid_get_serial_number_string.restype = ctypes.c_int
hidapi.hid_get_indexed_string.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_wchar_p,
    ctypes.c_size_t,
]
hidapi.hid_get_indexed_string.restype = ctypes.c_int
hidapi.hid_error.argtypes = [ctypes.c_void_p]
hidapi.hid_error.restype = ctypes.c_wchar_p


def enumerate(vid=0, pid=0):
    ret = []
    info = hidapi.hid_enumerate(vid, pid)
    c = info

    while c:
        ret.append(c.contents.as_dict())
        c = c.contents.next

    hidapi.hid_free_enumeration(info)

    return ret


def enumerate_unique(vid=0, pid=0, usage_page=0, usage=0):
    """Returns the current connected devices,
    sorted by path."""
    return sorted(
        list(
            {
                v["path"]: v
                for v in enumerate(vid, pid)
                if (not usage_page or usage_page == v.get("usage_page", None))
                and (not usage or usage == v.get("usage", None))
            }.values()
        ),
        key=lambda l: l["path"],
    )


class Device(object):
    def __init__(self, vid=None, pid=None, serial=None, path=None):
        if path:
            self._dev = hidapi.hid_open_path(path)
        elif serial:
            serial = ctypes.create_unicode_buffer(serial)
            self._dev = hidapi.hid_open(vid, pid, serial)
        elif vid and pid:
            self._dev = hidapi.hid_open(vid, pid, None)
        else:
            raise ValueError("specify vid/pid or path")

        if not self._dev:
            raise HIDException("unable to open device")

        # Reuse buffer as creating it every time is expensive
        # This means this process is no longer parallelizable, but you
        # should not be parallelizing it anyway
        self.buf = ctypes.create_string_buffer(MAX_REPORT_SIZE)

    @property
    def fd(self):
        if not self._dev:
            return 0
        return self._dev.contents.device_handle

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    def __hidcall(self, function, *args, **kwargs):
        if not self._dev:
            raise HIDException("device closed")

        ret = function(*args, **kwargs)

        if ret == -1:
            err = hidapi.hid_error(self._dev)
            raise HIDException(err)
        return ret

    def __readstring(self, function, max_length=255):
        buf = ctypes.create_unicode_buffer(max_length)
        self.__hidcall(function, self._dev, buf, max_length)
        return buf.value

    def write(self, data):
        return self.__hidcall(hidapi.hid_write, self._dev, data, len(data))

    def read(self, size: int = MAX_REPORT_SIZE, timeout=None):
        if timeout is None:
            size = self.__hidcall(hidapi.hid_read, self._dev, self.buf, size)
        else:
            size = self.__hidcall(
                hidapi.hid_read_timeout, self._dev, self.buf, size, timeout
            )

        return self.buf.raw[:size]

    def get_input_report(self, report_id, size: int = MAX_REPORT_SIZE):
        # Pass the id of the report to be read.
        self.buf[0] = bytearray((report_id,))

        size = self.__hidcall(hidapi.hid_get_input_report, self._dev, self.buf, size)
        return self.buf.raw[:size]

    def send_feature_report(self, data):
        return self.__hidcall(
            hidapi.hid_send_feature_report, self._dev, data, len(data)
        )

    def get_feature_report(self, report_id, size: int = MAX_REPORT_SIZE):
        # Pass the id of the report to be read.
        self.buf[0] = bytearray((report_id,))

        size = self.__hidcall(hidapi.hid_get_feature_report, self._dev, self.buf, size)
        return self.buf.raw[:size]

    def close(self):
        if self._dev:
            hidapi.hid_close(self._dev)
            self._dev = None

    @property
    def nonblocking(self):
        return getattr(self, "_nonblocking", 0)

    @nonblocking.setter
    def nonblocking(self, value):
        self.__hidcall(hidapi.hid_set_nonblocking, self._dev, value)
        setattr(self, "_nonblocking", value)

    @property
    def manufacturer(self):
        return self.__readstring(hidapi.hid_get_manufacturer_string)

    @property
    def product(self):
        return self.__readstring(hidapi.hid_get_product_string)

    @property
    def serial(self):
        return self.__readstring(hidapi.hid_get_serial_number_string)

    def get_indexed_string(self, index, max_length=255):
        buf = ctypes.create_unicode_buffer(max_length)
        self.__hidcall(hidapi.hid_get_indexed_string, self._dev, index, buf, max_length)
        return buf.value
