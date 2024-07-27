#!/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2024      Antheas Kapenekakis
# Copyright (c) 2012-2017 Benjamin Tissoires <benjamin.tissoires@gmail.com>
# Copyright (c) 2012-2017 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#


import copy
import enum
import functools
import itertools
import logging
import re
import os
import sys
from collections.abc import ItemsView, Iterable
from typing import (
    IO,
    Annotated,
    Any,
    Dict,
    Final,
    Hashable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Type,
    TypeAlias,
    Union,
    cast,
)

_Type = Type


class ValueRange(NamedTuple):
    min: int
    max: int


DATA_DIRNAME = "hid_data"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, DATA_DIRNAME)

U8 = Annotated[int, ValueRange(0, 0xFF)]
U16 = Annotated[int, ValueRange(0, 0xFFFF)]
U32 = Annotated[int, ValueRange(0, 0xFFFFFFFF)]

dict_items_usage: TypeAlias = ItemsView[U16, "HidUsage"]
dict_items_usagePage: TypeAlias = ItemsView[U16, "HidUsagePage"]


@functools.total_ordering
class HidUsage(Hashable):
    """
    A HID Usage entry as defined in the HID Usage Tablets. ::

        > usage_page = hidtools.hut.HUT[0x01]  # Generic Desktop
        > usage = usage_page[0x02]
        > print(usage.usage)
        2
        > print(usage)
        Mouse
        > print(usage.name)
        Mouse

    :param HidUsagePage usage_page: the Usage Page this Usage belongs to
    :param int usage: the 16-bit Usage assigned by the HID Usage Tables
    :param str name: the usage_name

    .. attribute:: usage

        the 16-bit Usage assigned by the HId Usage Tables

    .. attribute:: name

        the semantic name for this Usage

    .. attribute:: usage_page

        the :class:`HidUsagePage` this Usage belongs to

    """

    def __init__(
        self: "HidUsage", usage_page: "HidUsagePage", usage: U16, name: str
    ) -> None:
        self.usage_page = usage_page
        self.usage = usage
        self.name = name

    # Route everything down to the name, this way we basically behave like a
    # string
    def __getattr__(self: "HidUsage", attr: str) -> Any:
        return getattr(self.name, attr)

    def __repr__(self: "HidUsage") -> str:
        return self.name

    def __hash__(self: "HidUsage") -> int:
        return hash(self.name)

    def __str__(self: "HidUsage") -> str:
        return self.name

    def __eq__(self: "HidUsage", other: object) -> bool:
        if isinstance(other, HidUsage):
            return self.name == other.name
        elif not isinstance(other, str):
            return NotImplemented
        return self.name == other

    def __lt__(self: "HidUsage", other: object) -> bool:
        if isinstance(other, HidUsage):
            return self.name < other.name
        elif not isinstance(other, str):
            return NotImplemented
        return self.name < other


class HidUsagePage(object):
    """
    A dictionary of HID Usages in the form ``{usage: usage_name}``,
    representing all Usages in this Usage Page.

    A HID Usage is named semantical identifier that describe how a given
    field in a HID report is to be used. A Usage Page is a logical grouping
    of those identifiers, e.g. "Generic Desktop", "Telephony Devices", or
    "Digitizers".  ::

        > print(usage_page.page_name)
        Generic Desktop
        > print(usage_page.page_id)
        1
        > print(usage_page[0x02])
        Mouse
        > print(usage_page['Mouse'])
        Mouse
        > usage = usage_page.from_name["Mouse"]
        > print(usage.usage)
        2
        > print(usage.name)
        Mouse
        > print(usage)
        Mouse

    .. attribute:: page_id

        The Page ID for this Usage Page, e.g. ``01`` (Generic Desktop)

    .. attribute:: page_name

        The assigned name for this usage Page, e.g. "Generic Desktop"
    """

    def __init__(self: "HidUsagePage") -> None:
        self._usages: Dict[U16, HidUsage] = {}

    def __setitem__(self: "HidUsagePage", key: U16, value: HidUsage) -> None:
        self._usages[key] = value

    def __getitem__(self: "HidUsagePage", key: Union[str, U16, U32]) -> HidUsage:
        if isinstance(key, str):
            return self.from_name[key]

        # extract the usage if we have a 32-bit usage and the page ID
        # matches
        if key > 0xFFFF and key & 0xFFFF0000 == self.page_id << 16:
            key &= 0xFFFF
        return self._usages[key]

    def __delitem__(self: "HidUsagePage", key: U16) -> None:
        del self._usages[key]

    def __iter__(self: "HidUsagePage") -> Iterator[U16]:
        return iter(self._usages)

    def __len__(self: "HidUsagePage") -> int:
        return len(self._usages)

    def __str__(self: "HidUsagePage") -> str:
        return self.page_name

    def __repr__(self: "HidUsagePage") -> str:
        return self.page_name

    def items(self: "HidUsagePage") -> dict_items_usage:
        """
        Iterate over all elements, see :meth:`dict.items`
        """
        return self._usages.items()

    @property
    def page_id(self: "HidUsagePage") -> U16:
        """
        The numerical page ID for this usage page
        """
        return self._page_id

    @page_id.setter
    def page_id(self: "HidUsagePage", page_id: U16) -> None:
        self._page_id = page_id

    @property
    def page_name(self: "HidUsagePage") -> str:
        """
        The assigned name for this Usage Page
        """
        return self._name

    @page_name.setter
    def page_name(self: "HidUsagePage", name: str) -> None:
        self._name = name

    @property
    def from_name(self: "HidUsagePage") -> Dict[str, HidUsage]:
        """
        A dictionary using ``{ name: usage }`` mapping, to look up the
        :class:`HidUsage` based on a name.
        """
        try:
            return self._inverted
        except AttributeError:
            self._inverted: Dict[str, HidUsage] = {}
            for _, v in self.items():
                self._inverted[v.name] = v
            return self._inverted

    @property
    def from_usage(self: "HidUsagePage") -> Dict[U16, HidUsage]:
        """
        A dictionary using ``{ usage: name }`` mapping, to look up the name
        based on a page ID . This is the same as using the object itself.
        """
        return cast(Dict[U16, HidUsage], self)


class HidUsageTable(object):
    """
    This effectively a dictionary of all HID Usages known to man. Or to this
    module at least. This object is a singleton, it is available as
    ``hidtools.hut.HUT``.

    Elements of this dictionary are :class:`HidUsagePage` objects.

    This object is a dictionary, use like this: ::

        > hut = hidtools.hut.HUT
        > print(hut[0x01].page_name)
        Generic Desktop
        > print(hut['Generic Desktop'].page_name)
        Generic Desktop
        > print(hut.usage_pages[0x01].page_name)
        Generic Desktop
        > print(hut.usage_page_names['Generic Desktop'].page_name)
        Generic Desktop
        > print(hut[0x01].page_id)
        1
        > print(hut.usage_page_from_name('Generic Desktop').page_id)
        1
        > print(hut.usage_page_from_page_id(0x01).page_name)
        Generic Desktop
    """

    def __init__(self: "HidUsageTable") -> None:
        self._pages: Dict[U16, HidUsagePage] = {}

    def __setitem__(self: "HidUsageTable", key: U16, value: HidUsagePage) -> None:
        self._pages[key] = value

    def __getitem__(self: "HidUsageTable", key: Union[str, U16]) -> HidUsagePage:
        if isinstance(key, str):
            return self.usage_page_names[key]

        # shift the usage page bits down if we have a 32-bit usage
        if key & 0xFFFF0000 == key:
            key >>= 16
        return self._pages[key]

    def __delitem__(self: "HidUsageTable", key) -> None:
        del self._pages[key]

    def __iter__(self: "HidUsageTable") -> Iterator[HidUsagePage]:
        return iter(self._pages)

    def __len__(self: "HidUsageTable") -> int:
        return len(self._pages)

    def items(self: "HidUsageTable") -> dict_items_usagePage:
        """
        Iterate over all elements, see :meth:`dict.items`
        """
        return self._pages.items()

    @property
    def usage_pages(self: "HidUsageTable") -> Dict[U16, HidUsagePage]:
        """
        A dictionary mapping ``{page_id : object}``. These two are
        equivalent calls: ::

            HUT[0x1]
            HUT.usage_pages[0x1]

        """
        return self._pages

    @property
    def usage_page_names(self: "HidUsageTable") -> Dict[str, HidUsagePage]:
        """
        A dictionary mapping ``{page_name : object}``. These two are
        equivalent calls: ::

            HUT['Generic Desktop']
            HUT.usage_page_names['Generic Desktop']

        """
        return {v.page_name: v for _, v in self.items()}

    def usage_page_from_name(
        self: "HidUsageTable", page_name: str
    ) -> Optional[HidUsagePage]:
        """
        Look up the usage page based on the page name (e.g. "Generic
        Desktop"). This is identical to ::

            self.usage_page_names[page_name]

        except that this function returns ``None`` if the page name is
        unknown.

        :return: the :meth:`HidUsagePage` or None
        """
        try:
            return self[page_name]
        except KeyError:
            return None

    def usage_page_from_page_id(
        self: "HidUsageTable", page_id: U16
    ) -> Optional[HidUsagePage]:
        """
        Look up the usage page based on the page ID. This is identical to ::

                self.usage_pages[page_id]

        except that this function returns ``None`` if the page ID is unknown.

        :return: the :meth:`HidUsagePage` or None
        """
        try:
            return self[page_id]
        except KeyError:
            return None

    @classmethod
    def _parse_usages(cls: Type["HidUsageTable"], f: Iterable[str]) -> HidUsagePage:
        """
        Parse a single HUT file. The file format is a set of lines in three
        formats: ::

            (01)<tab>Usage Page name
            A0<tab>Name
            F0-FF<tab>Reserved for somerange

        All numbers in hex.

        Only one Usage Page per file

        Usages are parsed into a dictionary[number] = name.

        The return value is a single HidUsagePage where page[idx] = idx-name.
        """
        usage_page = None
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Usage Page, e.g. '(01)	Generic Desktop'
            if line.startswith("("):
                assert usage_page is None

                r = re.match(r"\((?P<idx>[0-9a-fA-F]+)\)\t(?P<page_name>.+)", line)
                assert r is not None
                usage_page = HidUsagePage()
                usage_page.page_id = r["idx"]  # type: ignore
                usage_page.page_name = r["page_name"]
                continue

            assert usage_page is not None

            # Reserved ranges, e.g  '0B-1F	Reserved'
            # "{:x}-{:x}\t{name}"
            r = re.match(
                r"(?P<start>[0-9a-fA-FxX]+)-(?P<end>[0-9a-fA-FxX]+)\S+(?P<name>.+)",
                line,
            )
            if r:
                if "reserved" not in r["name"].lower():
                    print(line)
                continue

            # Single usage, e.g. 36	Slider
            r = re.match(r"(?P<usage>[0-9a-fA-FxX]+)\S+(?P<name>.+)", line)
            assert r is not None, f'"{line}"'
            if "reserved" in r["name"].lower():
                continue

            u = int(r["usage"], 16)
            usage = HidUsage(usage_page, u, r["name"])

            usage_page[u] = usage

        if usage_page is None:
            raise Exception

        return usage_page

    @classmethod
    def _from_hut_data(cls: Type["HidUsageTable"]) -> "HidUsageTable":
        """
        Return the HID Usage Tables, the keys are the numeric Usage Page and
        the values are the respective :class:`hidtools.HidUsagePage` object.

        ::

            > usages = hidtools.hut.HUT()
            > print(usages[0x01].page_name)
            Generic Desktop
            > print(usages.usage_pages[0x01].page_name)
            Generic Desktop
            > print(usages[0x01].page_id)
            1

        :return: a :class:`hidtools.HidUsageTable` object
        """
        hut = HidUsageTable()
        for filename in os.listdir(DATA_DIR):
            if filename.endswith(".hut"):
                with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
                    try:
                        usage_page = cls._parse_usages(f)
                        hut[usage_page.page_id] = usage_page
                    except:
                        print(filename)
                        raise

        return hut


HUT = HidUsageTable._from_hut_data()
"""
The HID Usage Tables as a :class:`hidtools.HidUsageTable` object,
a dictionary where the keys are the numeric Usage Page and the values are
the respective :class:`hidtools.HidUsagePage` object. ::

    > usages = hidtools.hut.HUT()
    > print(usages[0x01].page_name)
    Generic Desktop
    > print(usages.usage_pages[0x01].page_name)
    Generic Desktop
    > print(usages[0x01].page_id)
    1
"""


class BusType(enum.IntEnum):
    """
    The numerical bus type (``0x3`` for USB, ``0x5`` for Bluetooth, see
        ``linux/input.h``)
    """

    PCI = 0x01
    ISAPNP = 0x02
    USB = 0x03
    HIL = 0x04
    BLUETOOTH = 0x05
    VIRTUAL = 0x06
    ISA = 0x10
    I8042 = 0x11
    XTKBD = 0x12
    RS232 = 0x13
    GAMEPORT = 0x14
    PARPORT = 0x15
    AMIGA = 0x16
    ADB = 0x17
    I2C = 0x18
    HOST = 0x19
    GSC = 0x1A
    ATARI = 0x1B
    SPI = 0x1C
    RMI = 0x1D
    CEC = 0x1E
    INTEL_ISHTP = 0x1F
    AMD_SFH = 0x20


def twos_comp(val, bits):
    """compute the 2's complement of val.

    :param int val:
        the value to compute the two's complement for

    :param int bits:
        size of val in bits
    """
    if bits and (val & (1 << (bits - 1))) != 0:
        val = val - (1 << bits)
    return val


def to_twos_comp(val, bits):
    return val & ((1 << bits) - 1)


logger = logging.getLogger("hidtools.hid")

# mypy is confused by the various .bytes properties, so redefine the bytes type
Bytes: TypeAlias = bytes

hid_items: Final = {
    "Main": {
        "Input": 0b10000000,  # noqa: E203
        "Output": 0b10010000,  # noqa: E203
        "Feature": 0b10110000,  # noqa: E203
        "Collection": 0b10100000,  # noqa: E203
        "End Collection": 0b11000000,  # noqa: E203
    },
    "Global": {
        "Usage Page": 0b00000100,  # noqa: E203
        "Logical Minimum": 0b00010100,  # noqa: E203
        "Logical Maximum": 0b00100100,  # noqa: E203
        "Physical Minimum": 0b00110100,  # noqa: E203
        "Physical Maximum": 0b01000100,  # noqa: E203
        "Unit Exponent": 0b01010100,  # noqa: E203
        "Unit": 0b01100100,  # noqa: E203
        "Report Size": 0b01110100,  # noqa: E203
        "Report ID": 0b10000100,  # noqa: E203
        "Report Count": 0b10010100,  # noqa: E203
        "Push": 0b10100100,  # noqa: E203
        "Pop": 0b10110100,  # noqa: E203
    },  # noqa: E203
    "Local": {
        "Usage": 0b00001000,  # noqa: E203
        "Usage Minimum": 0b00011000,  # noqa: E203
        "Usage Maximum": 0b00101000,  # noqa: E203
        "Designator Index": 0b00111000,  # noqa: E203
        "Designator Minimum": 0b01001000,  # noqa: E203
        "Designator Maximum": 0b01011000,  # noqa: E203
        "String Index": 0b01111000,  # noqa: E203
        "String Minimum": 0b10001000,  # noqa: E203
        "String Maximum": 0b10011000,  # noqa: E203
        "Delimiter": 0b10101000,  # noqa: E203
    },
}

superscripts: Final = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "-": "⁻",
}


class HidUnit(object):
    """
    A parsed field of a HID Report Descriptor Unit specification.

    .. attribute:: units

        A dict of { unit: exponent } of the applicable units.
        Where the Unit is ``None``, the return value is ``None``.

    .. attribute:: system

        The system the units belong to, one of :class:`HidUnit.System`.

    """

    NONE: Final = cast("HidUnit", None)  # For Unit(None), makes the code more obvious

    class System(enum.IntEnum):
        NONE = 0
        SI_LINEAR = 1
        SI_ROTATION = 2
        ENGLISH_LINEAR = 3
        ENGLISH_ROTATION = 4

        @classmethod
        def _stringmap(cls: _Type["HidUnit.System"]) -> Dict["HidUnit.System", str]:
            return {
                HidUnit.System.NONE: "None",
                HidUnit.System.SI_LINEAR: "SILinear",
                HidUnit.System.SI_ROTATION: "SIRotation",
                HidUnit.System.ENGLISH_LINEAR: "EnglishLinear",
                HidUnit.System.ENGLISH_ROTATION: "EnglishRotation",
            }

        def __str__(self: "HidUnit.System") -> str:
            return self._stringmap()[self]

        @classmethod
        def from_string(
            cls: _Type["HidUnit.System"], string: str
        ) -> Optional["HidUnit.System"]:
            """
            Returns the correct :class:`HidUnit.System` given the string.
            """
            try:
                return {v: k for k, v in cls._stringmap().items()}[string]
            except KeyError:
                return None

        @property
        def length(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the length measurement in
            this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.CENTIMETER,
                HidUnit.System.SI_ROTATION: Unit.RADIANS,
                HidUnit.System.ENGLISH_LINEAR: Unit.INCH,
                HidUnit.System.ENGLISH_ROTATION: Unit.DEGREES,
            }[self]

        @property
        def mass(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the mass measurement in
            this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.GRAM,
                HidUnit.System.SI_ROTATION: Unit.GRAM,
                HidUnit.System.ENGLISH_LINEAR: Unit.SLUG,
                HidUnit.System.ENGLISH_ROTATION: Unit.SLUG,
            }[self]

        @property
        def time(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the time measurement in
            this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.SECONDS,
                HidUnit.System.SI_ROTATION: Unit.SECONDS,
                HidUnit.System.ENGLISH_LINEAR: Unit.SECONDS,
                HidUnit.System.ENGLISH_ROTATION: Unit.SECONDS,
            }[self]

        @property
        def temperature(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the temperature measurement
            in this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.KELVIN,
                HidUnit.System.SI_ROTATION: Unit.KELVIN,
                HidUnit.System.ENGLISH_LINEAR: Unit.FAHRENHEIT,
                HidUnit.System.ENGLISH_ROTATION: Unit.FAHRENHEIT,
            }[self]

        @property
        def current(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the current measurement
            in this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.AMPERE,
                HidUnit.System.SI_ROTATION: Unit.AMPERE,
                HidUnit.System.ENGLISH_LINEAR: Unit.AMPERE,
                HidUnit.System.ENGLISH_ROTATION: Unit.AMPERE,
            }[self]

        @property
        def luminous_intensity(self: "HidUnit.System") -> Optional["Unit"]:
            """
            Returns the right :class:`Unit` for the luminous intensity
            measurement in this system.
            """
            return {
                HidUnit.System.NONE: None,
                HidUnit.System.SI_LINEAR: Unit.CANDELA,
                HidUnit.System.SI_ROTATION: Unit.CANDELA,
                HidUnit.System.ENGLISH_LINEAR: Unit.CANDELA,
                HidUnit.System.ENGLISH_ROTATION: Unit.CANDELA,
            }[self]

    def __init__(
        self: "HidUnit", system: "HidUnit.System", units: Dict[Optional["Unit"], U16]
    ) -> None:
        self.units = units
        self.system = system

    @classmethod
    def _parse(cls: _Type["HidUnit"], data: Bytes) -> "HidUnit":
        assert data and len(data) >= 1

        def nibbles(data):
            for element in data:
                yield element & 0xF
                yield (element >> 4) & 0xF

        systems = (
            "System",
            "Length",
            "Mass",
            "Time",
            "Temperature",
            "Current",
            "Intensity",
            "Reserved",
        )

        # Creates a dict with the type of system as key and the value of the
        # nibble (the exponent) as value.
        exponents = dict(itertools.zip_longest(systems, nibbles(data)))
        system = HidUnit.System(exponents["System"])
        if system == HidUnit.System.NONE:
            return HidUnit.NONE

        def convert(exponent: Optional[U16]) -> Optional[U16]:
            return twos_comp(exponent, 4) if exponent is not None else None

        # Now create the mapping of correct unit types with their exponents, e.g.
        # {CENTIMETER: 2, SECONDS: -1}.
        units = {
            # system: convert(exponents['System']),
            system.length: convert(exponents["Length"]),
            system.mass: convert(exponents["Mass"]),
            system.time: convert(exponents["Time"]),
            system.temperature: convert(exponents["Temperature"]),
            system.current: convert(exponents["Current"]),
            system.luminous_intensity: convert(exponents["Intensity"]),
        }

        # Filter out any parts that aren't set
        units = {k: v for k, v in units.items() if v is not None and v}
        if units:
            return HidUnit(system, units)  # type: ignore ### bug in mypy it detects v from above as U16 | None
        else:
            return HidUnit.NONE

    @classmethod
    def from_bytes(cls: _Type["HidUnit"], data: Bytes) -> "HidUnit":
        """
        Converts the given data bytes into a :class:`HidUnit` object.
        The data bytes must not include the 0b011001nn prefix byte.

        Where the HID unit system is None, the returned value is None.
        """
        assert 1 <= len(data) <= 4
        return HidUnit._parse(data)

    @classmethod
    def from_value(cls: _Type["HidUnit"], value: Union[U8, U16, U32]) -> "HidUnit":
        """
        Converts the given 8, 16 or 32-bit value into a :class:`HidUnit`
        object.

        Where the HID unit system is None, the returned value is None.
        """
        assert value <= 0xFFFFFFFF
        return cls.from_bytes(value.to_bytes(byteorder="little", length=4))

    def __eq__(self: "HidUnit", other: Any) -> bool:
        if not isinstance(other, HidUnit):
            raise NotImplementedError
        return self.system == other.system and self.units == other.units

    def __str__(self: "HidUnit") -> str:
        units = []
        for u, exp in self.units.items():
            if exp == 1:
                s = ""
            else:
                s = "".join([superscripts[c] for c in str(exp)])
            if u is not None:
                units.append((u.value, s))

        # python 3.6 seems to not use __str__() for enums, leading to errors
        # in the test suite
        return f"{str(self.system)}: " + " * ".join(
            (f"{unit}{exp}" for unit, exp in units)
        )

    @classmethod
    def from_string(cls: _Type["HidUnit"], string: str) -> "HidUnit":
        """
        The inverse of __str__()
        """
        system_string, unit_string = string.split(": ")
        system = HidUnit.System.from_string(system_string)
        if system is None:
            return HidUnit.NONE

        unitstrings = unit_string.split(" * ")
        units: Dict[Optional["Unit"], U16] = {}
        for s in unitstrings:
            match: Optional[re.Match[str]]
            match = re.match(r"(?P<unit>[a-zA-z]+)(?P<exp>[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]{1,})?", s)
            if match is None:
                continue
            unitstring, expstring = match["unit"], match["exp"]

            unit = Unit(unitstring)
            ssinv = {v: k for k, v in superscripts.items()}
            if expstring:
                exponent = int("".join([ssinv[c] for c in expstring]))
            else:
                exponent = 1

            units[unit] = exponent
        return HidUnit(system, units)

    @property
    def value(self: "HidUnit") -> U32:
        """
        Returns the numerical value for this unit as required by the HID
        specification.
        """
        v = self.system.value

        def unit_value(unit_type):
            if unit_type in self.units:
                return to_twos_comp(self.units[unit_type], 4)
            return 0

        v |= unit_value(self.system.length) << 4
        v |= unit_value(self.system.mass) << 8
        v |= unit_value(self.system.time) << 12
        v |= unit_value(self.system.temperature) << 16
        v |= unit_value(self.system.current) << 20
        v |= unit_value(self.system.luminous_intensity) << 24
        return v


class HidCollection:
    class Type(enum.IntEnum):
        PHYSICAL = 0
        APPLICATION = 1
        LOGICAL = 2
        REPORT = 3
        NAMED_ARRAY = 4
        USAGE_SWITCH = 5
        USAGE_MODIFIER = 6

    def __init__(self: "HidCollection", value: U8) -> None:
        assert value <= 0xFF
        self.value = value
        self.name = str(self)
        self.type: Optional[HidCollection.Type]
        try:
            self.type = HidCollection.Type(value)
        except ValueError:
            self.type = None

    @property
    def is_reserved(self: "HidCollection") -> bool:
        return 0x07 <= self.value <= 0x7F

    @property
    def is_vendor_defined(self: "HidCollection") -> bool:
        return 0x80 <= self.value <= 0xFF

    @classmethod
    def from_str(cls: _Type["HidCollection"], string: str) -> U16:
        """
        Return the value of this HidCollection given the human-readable
        string
        """
        for v in HidCollection.Type:
            if v.name == string.strip().upper():
                return v.value
        match = re.match(
            r"\s*(vendor[ -_]defined)\s+(0x|x)?(?P<value>[0-9a-f]{2,})",
            string,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError(f"Invalid HidCollection: {string}")

        return int(match["value"], 16)

    def __str__(self: "HidCollection") -> str:
        try:
            return HidCollection.Type(self.value).name
        except ValueError:
            if self.is_reserved:
                c = f"RESERVED {self.value:#x}"
            elif self.is_vendor_defined:
                c = f"VENDOR_DEFINED {self.value:#x}"
            else:  # not supposed to happen
                raise
            return c


sensor_mods: Final = {
    0x00: "Mod None",
    0x10: "Mod Change Sensitivity Abs",
    0x20: "Mod Max",
    0x30: "Mod Min",
    0x40: "Mod Accuracy",
    0x50: "Mod Resolution",
    0x60: "Mod Threshold High",
    0x70: "Mod Threshold Low",
    0x80: "Mod Calibration Offset",
    0x90: "Mod Calibration Multiplier",
    0xA0: "Mod Report Interval",
    0xB0: "Mod Frequency Max",
    0xC0: "Mod Period Max",
    0xD0: "Mod Change Sensitivity Range Percent",
    0xE0: "Mod Change Sensitivity Rel Percent",
    0xF0: "Mod Vendor Reserved",
}

inv_hid: Dict[U16, str] = {}  # e.g 0b10000000 : "Input"
hid_type: Dict[str, str] = {}  # e.g. "Input" : "Main"
for type, items in hid_items.items():
    for k, v in items.items():
        inv_hid[v] = k
        hid_type[k] = type


class ParseError(Exception):
    """Exception thrown during report descriptor parsing"""

    pass


class RangeError(Exception):
    """Exception thrown for an out-of-range value

    .. attribute:: value

        The invalid value

    .. attribute:: range

        A ``(min, max)`` tuple for the allowed logical range

    .. attribute:: field

        The :class:`HidField` that triggered this exception
    """

    def __init__(self: "RangeError", field: "HidField", value: int) -> None:
        self.field = field
        self.range = field.logical_min, field.logical_max
        self.value = value

    def __str__(self: "RangeError") -> str:
        min, max = self.range
        return f"Value {self.value} is outside range {min}, {max} for {self.field.usage_name}"


class Unit(enum.Enum):
    CENTIMETER = "cm"
    RADIANS = "rad"
    INCH = "in"
    DEGREES = "deg"
    GRAM = "g"
    SLUG = "slug"
    SECONDS = "s"
    KELVIN = "K"
    FAHRENHEIT = "F"
    AMPERE = "A"
    CANDELA = "cd"
    RESERVED = "reserved"


class HidField(object):
    """
    Represents one field in a HID report. A field is one element of a HID
    report that matches a specific set of bits in that report.

    .. attribute:: usage

        The numerical HID field's Usage, e.g. 0x38 for "Wheel". If the field
        has multiple usages, this refers to the first one.

    .. attribute:: usage_page

        The numerical HID field's Usage Page, e.g. 0x01 for "Generic
        Desktop"

    .. attribute:: report_ID

        The numeric Report ID this HID field belongs to

    .. attribute:: logical_min

        The logical minimum of this HID field

    .. attribute:: logical_max

        The logical maximum of this HID field

    .. attribute:: physical_min

        The physical minimum of this HID field

    .. attribute:: physical_max

        The physical maximum of this HID field

    .. attribute:: unit

        The unit of this HID field

    .. attribute:: unit_exp

        The unit exponent of this HID field

    .. attribute:: size

        Report Size in bits for this HID field

    .. attribute:: count

        Report Count for this HID field
    """

    def __init__(
        self: "HidField",
        report_ID: U8,
        logical: Optional[U32],
        physical: Optional[U32],
        application: Optional[U32],
        collection: Optional[Tuple[U32, U32, U32]],
        value: U32,
        usage_page: U16,
        usage: U32,
        logical_min: U32,
        logical_max: U32,
        physical_min: U32,
        physical_max: U32,
        unit: U16,
        unit_exp: U8,
        item_size: U8,
        count: U8,
    ) -> None:
        self.report_ID = report_ID
        self.logical = logical
        self.physical = physical
        self.application = application
        self.collection = collection
        self.type = value
        self.usage_page = usage_page
        self.usage = usage
        self.usages: Optional[List[U32]] = None
        self.logical_min = logical_min
        self.logical_max = logical_max
        self.physical_min = physical_min
        self.physical_max = physical_max
        self.unit = unit
        self.unit_exp = unit_exp
        self.size = item_size
        self.count = count
        self.start = 0

    def copy(self: "HidField") -> "HidField":
        """
        Return a full copy of this :class:`HIDField`.
        """
        c = copy.copy(self)
        if self.usages is not None:
            c.usages = self.usages[:]
        return c

    def _usage_name(self: "HidField", usage: U32) -> str:
        usage_page: U16 = usage >> 16
        value: U16 = usage & 0x0000FFFF
        if usage_page in HUT:  # type: ignore ### Operator "in" not supported for types "int" and "HidUsageTable"
            if HUT[usage_page].page_name == "Button":
                name = f"B{str(value)}"
            else:
                try:
                    name = HUT[usage_page][value].name
                except KeyError:
                    name = f"0x{usage:04x}"
        else:
            name = f"0x{usage:04x}"
        return name

    @property
    def usage_name(self: "HidField") -> str:
        """
        The Usage name for this field (e.g. "Wheel").
        """
        return self._usage_name(self.usage)

    def get_usage_name(self: "HidField", index: int) -> Optional[str]:
        """
        Return the Usage name for this field at the given index. Use this
        function when the HID field has multiple Usages.
        """
        if self.usages is not None:
            return self._usage_name(self.usages[index])
        return None

    @property
    def physical_name(self: "HidField") -> Optional[str]:
        """
        The physical name or ``None``
        """
        phys = self.physical
        if phys is None:
            return phys

        _phys = ""
        try:
            page_id = phys >> 16
            value = phys & 0xFF
            _phys = HUT[page_id][value].name
        except KeyError:
            try:
                _phys = f"0x{phys:04x}"
            except ValueError:
                pass
        return _phys

    @property
    def logical_name(self: "HidField") -> Optional[str]:
        """
        The logical name or ``None``
        """
        logical = self.logical
        if logical is None:
            return None

        _logical = ""

        try:
            page_id = logical >> 16
            value = logical & 0xFF
            _logical = HUT[page_id][value].name
        except KeyError:
            try:
                _logical = f"0x{logical:04x}"
            except ValueError:
                pass
        return _logical

    def _get_value(self: "HidField", report: List[U8], idx: int) -> Union[U32, str]:
        """
        Extract the bits that are this HID field in the list of bytes
        ``report``

        :param list report: a list of bytes that represent a HID report
        :param int idx: which field index to fetch, only greater than 0 if
            :attr:`count` is larger than 1
        """
        value = 0
        start_bit = self.start + self.size * idx
        end_bit = start_bit + self.size * (idx + 1)
        data = report[int(start_bit / 8) : int(end_bit / 8 + 1)]
        if len(data) == 0:
            return "<.>"
        for d in range(len(data)):
            value |= data[d] << (8 * d)

        bit_offset = start_bit % 8
        value = value >> bit_offset
        garbage = (value >> self.size) << self.size
        value = value - garbage
        if self.logical_min < 0 and self.size > 1:
            value = twos_comp(value, self.size)
        return value

    def get_values(self: "HidField", report: List[U8]) -> List[Union[U32, str]]:
        """
        Assume ``report`` is a list of bytes that are a full HID report,
        extract the values that are this HID field.

        Example:

        - if this field is Usage ``X`` , this returns ``[x-value]``
        - if this field is Usage ``X``, ``Y``, this returns ``[x, y]``
        - if this field is a button mask, this returns ``[1, 0, 1, ...]``, i.e. one value for each
          button

        :param list report: a list of bytes that are a HID report
        :returns: a list of integer values of len :attr:`count`
        """
        return [self._get_value(report, i) for i in range(self.count)]

    def _fill_value(self: "HidField", report: List[U8], value: U32, idx: int) -> None:
        start_bit = self.start + self.size * idx
        n = self.size

        max = (1 << n) - 1
        if value > max:
            raise Exception(
                f"_set_value(): value {value} is larger than size {self.size}"
            )

        byte_idx = int(start_bit / 8)
        bit_shift = start_bit % 8
        bits_to_set = 8 - bit_shift

        while n - bits_to_set >= 0:
            report[byte_idx] &= ~(0xFF << bit_shift)
            report[byte_idx] |= (value << bit_shift) & 0xFF
            value >>= bits_to_set
            n -= bits_to_set
            bits_to_set = 8
            bit_shift = 0
            byte_idx += 1

        # last nibble
        if n:
            bit_mask = (1 << n) - 1
            report[byte_idx] &= ~(bit_mask << bit_shift)
            report[byte_idx] |= value << bit_shift

    def fill_values_array(self: "HidField", report: List[U8], data: List[Any]) -> None:
        """
        Assuming ``data`` is the value for this HID field array and ``report``
        is a HID report's bytes, this method sets those bits in ``report`` that
        are his HID field to ``value``.

        Example:
        - if this field is an array of keys, use
          ``fill_values(report, ['a or A', 'b or B', ...]``, i.e. one string
          representation for each pressed key


        ``data`` must have at most :attr:`count` elements, matching this
        field's Report Count.


        :param list report: an integer array representing this report,
            modified in place
        :param list data: the data for this hid field with one element for
            each Usage.
        """
        if len(data) > self.count:
            raise Exception("-EINVAL")

        array: List[int] = []

        for usage_name in data:
            try:
                usage = HUT[self.usage_page].from_name[usage_name]
            except KeyError:
                continue

            full_usage = usage.usage_page.page_id << 16 | usage.usage

            if self.usages is not None and full_usage in self.usages:
                idx = self.usages.index(full_usage)
                array.append(idx)

        for idx in range(self.count):
            try:
                v = array[idx]
            except IndexError:
                v = 0

            v += self.logical_min

            self._fill_value(report, v, idx)

    def fill_values(self: "HidField", report: List[U8], data: List[U32]) -> None:
        """
        Assuming ``data`` is the value for this HID field and ``report`` is
        a HID report's bytes, this method sets those bits in ``report`` that
        are his HID field to ``value``.

        Example:

        - if this field is Usage ``X`` , use ``fill_values(report, [x-value])``
        - if this field is Usage ``X``, ``Y``, use ``fill_values(report, [x, y])``
        - if this field is a button mask, use
          ``fill_values(report, [1, 0, 1, ...]``, i.e. one value for each
          button

        ``data`` must have at least :attr:`count` elements, matching this
        field's Report Count.


        :param list report: an integer array representing this report,
            modified in place
        :param list data: the data for this hid field with one element for
            each Usage.
        """
        if len(data) != self.count:
            raise Exception("-EINVAL")

        for idx in range(self.count):
            v = data[idx]

            if self.is_null:
                # FIXME: handle the signed case too
                if v >= (1 << self.size):
                    raise RangeError(self, v)
            elif self.usage_name not in ["Contact Id", "Contact Max", "Contact Count"]:
                if v and not (self.logical_min <= v <= self.logical_max):
                    raise RangeError(self, v)
            if self.logical_min < 0:
                v = to_twos_comp(v, self.size)
            self._fill_value(report, v, idx)

    @property
    def is_array(self: "HidField") -> bool:
        """
        ``True`` if this HID field is an array
        """
        return not (self.type & (0x1 << 1))  # Variable

    @property
    def is_const(self: "HidField") -> bool:
        """
        ``True`` if this HID field is const
        """
        return bool(self.type & (0x1 << 0))

    @property
    def is_null(self: "HidField") -> bool:
        """
        ``True`` if this HID field is null
        """
        return bool(self.type & (0x1 << 6))

    @property
    def usage_page_name(self: "HidField") -> str:
        """
        The Usage Page name for this field, e.g. "Generic Desktop"
        """
        usage_page_name = ""
        usage_page = self.usage_page >> 16
        try:
            usage_page_name = HUT[usage_page].page_name
        except KeyError:
            pass
        return usage_page_name

    @classmethod
    def getHidFields(
        cls: _Type["HidField"],
        report_ID: U8,
        logical: Optional[U32],
        physical: Optional[U32],
        application: Optional[U32],
        collection: Optional[Tuple[U32, U32, U32]],
        value: U32,
        usage_page: U16,
        usages: List[U32],
        usage_min: U32,
        usage_max: U32,
        logical_min: U32,
        logical_max: U32,
        physical_min: U32,
        physical_max: U32,
        unit: U16,
        unit_exp: U8,
        item_size: U8,
        count: int,
    ):
        """
        This is a function to be called by a HID report descriptor parser.

        Given the current parser state and the various arguments, create the
        required number of :class:`HidField` objects.

        :returns: a list of :class:`HidField` objects
        """

        # Note: usage_page is a 32-bit value here and usage
        # is usage_page | usage

        usage: U32 = usage_min
        if len(usages) > 0:
            usage = usages[0]

        # for arrays, we don't have a given usage
        # use either the logical if given or the application
        if not value & 0x3:
            if logical is not None and logical:
                usage = logical
            elif application is not None:
                usage = application

        item = cls(
            report_ID,
            logical,
            physical,
            application,
            collection,
            value,
            usage_page,
            usage,
            logical_min,
            logical_max,
            physical_min,
            physical_max,
            unit,
            unit_exp,
            item_size,
            1,
        )
        items = []

        if value & 0x3:  # Const or Variable item
            if usage_min and usage_max:
                usage = usage_min
                for i in range(count):
                    item = item.copy()
                    item.usage = usage
                    items.append(item)
                    if usage < usage_max:
                        usage += 1
            elif usages:
                for i in range(count):
                    if i < len(usages):
                        usage = usages[i]
                    else:
                        usage = usages[-1]
                    item = item.copy()
                    item.usage = usage
                    items.append(item)
            # A const field used for padding may not have any usages
            else:
                item.size *= count
                return [item]
        else:  # Array item
            if usage_min and usage_max:
                usages = list(range(usage_min, usage_max + 1))
            item.usages = usages
            item.count = count
            return [item]
        return items


class HidReport(object):
    """
    Represents a HidReport, one of ``Input``, ``Output``, ``Feature``. A
    :class:`ReportDescriptor` may contain one or more
    HidReports of different types. These comprise of a number of
    :class:`HidField` making up the exact description of a
    report.

    :param int report_ID: the report ID
    :param int application: the HID application

    .. attribute:: fields

        The :class:`HidField` elements comprising this report

    """

    class Type(enum.Enum):
        """The type of a :class:`HidReport`"""

        INPUT = enum.auto()
        OUTPUT = enum.auto()
        FEATURE = enum.auto()

    def __init__(
        self: "HidReport",
        report_ID: U8,
        application: Optional[U32],
        type: "HidReport.Type",
    ) -> None:
        self.fields: List[HidField] = []
        self.report_ID = report_ID
        self.application = application
        self._application_name: Optional[str] = None
        self._bitsize = 0
        if self.numbered:
            self._bitsize = 8
        self._type = type
        self.prev_collection: Optional[Tuple[U32, U32, U32]] = None

    def append(self: "HidReport", field: HidField) -> None:
        """
        Add a :class:`HidField` to this report

        :param HidField field: the object to add to this report
        """
        self.fields.append(field)
        field.start = self._bitsize
        self._bitsize += field.size

    def extend(self: "HidReport", fields: List[HidField]) -> None:
        """
        Extend this report by the list of :class:`HidField`
        objects

        :param list fields: a list of objects to append to this report
        """
        self.fields.extend(fields)
        for f in fields:
            f.start = self._bitsize
            self._bitsize += f.size * f.count

    @property
    def application_name(self: "HidReport") -> str:
        if self.application is None:
            return "Vendor"

        try:
            page_id = self.application >> 16
            value = self.application & 0xFF
            return HUT[page_id][value].name
        except KeyError:
            return "Vendor"

    @property
    def type(self: "HidReport") -> "HidReport.Type":
        """
        One of the types in :class:`HidReport.Type`
        """
        return self._type

    @property
    def numbered(self: "HidReport") -> bool:
        """
        True if the HidReport was initialized with a report ID
        """
        return self.report_ID >= 0

    @property
    def bitsize(self: "HidReport") -> int:
        """
        The size of the HidReport in bits
        """
        return self._bitsize

    @property
    def size(self: "HidReport") -> int:
        """
        The size of the HidReport in bytes
        """
        return self._bitsize >> 3


class _HidRDescItem(object):
    """
    Represents one item in the Report Descriptor. This is a variable-sized
    element with one header byte and 0, 1, 2, 4 payload bytes.

    :param int index_in_report:
        The index within the report descriptor
    :param int hid:
        The numerical hid type (e.g. ``0b00000100`` for Usage Page)
    :param int value:
        The 8, 16, or 32 bit value
    :param list raw_values:
        The payload bytes' raw values, LSB first


    These items are usually parsed from a report descriptor, see
    :meth:`from_bytes`. The report descriptor
    bytes are::

                H P P H H P H P

    where each header byte looks like this

    +---------+---+---+---+---+---+---+---+---+
    | bit     | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
    +=========+===+===+===+===+===+===+===+===+
    |         |   hid item type       | size  |
    +---------+-----------------------+-------+

    .. note:: a size of 0x3 means payload size 4

    To create a _HidRDescItem from a human-readable description, use
    :meth:`from_human_descr`.



    .. attribute:: index_in_report

        The numerical index of this item in the report descriptor.

    .. attribute:: raw_value

        A list of the payload's raw values

    .. attribute:: hid

        The hid item as number (e.g. ``0b00000100`` for Usage Page)

    .. attribute:: item

        The hid item as string (e.g. "Usage Page")

    .. attribute:: value

        The payload value as single number

    """

    def __init__(
        self: "_HidRDescItem",
        index_in_report: int,
        hid: U16,
        value: int,
        raw_values: List[U8],
    ) -> None:
        self.index_in_report = index_in_report
        self.raw_value = raw_values
        self.hid = hid
        self.value = value
        self.usage_page: U16 = 0
        try:
            self.item = inv_hid[self.hid]
        except KeyError:
            error = f"error while parsing {hid:02x}"
            raise KeyError(error)

        if self.item in (
            "Logical Minimum",
            "Physical Minimum",
            # "Logical Maximum",
            # "Physical Maximum",
        ):
            self._twos_comp()
        if self.item == "Unit Exponent" and self.value > 7:
            self.value -= 16

    def _twos_comp(self: "_HidRDescItem") -> int:
        self.value = twos_comp(self.value, (self.size - 1) * 8)
        return self.value

    @property
    def size(self: "_HidRDescItem") -> int:
        """The size in bytes, including header byte"""
        return 1 + len(self.raw_value)

    @property
    def bytes(self: "_HidRDescItem") -> List[U8]:
        """
        Return this in the original format in bytes, i.e. a header byte
        followed by (if any) payload bytes.

        :returns: a list of bytes that are this item
        """
        if len(self.raw_value) == 4:
            h = self.hid | 0x3
        else:
            h = self.hid | len(self.raw_value)
        return [h] + self.raw_value.copy()

    def __repr__(self: "_HidRDescItem") -> str:
        data = [f"{i:02x}" for i in self.bytes]
        return f'{" ".join(data)}'

    def _get_raw_values(self: "_HidRDescItem") -> str:
        """The raw values as comma-separated hex numbers"""
        data = str(self)
        # prefix each individual value by "0x" and insert "," in between
        data = f'0x{data.replace(" ", ", 0x")},'
        return data

    def get_human_descr(self: "_HidRDescItem", indent: int) -> Tuple[str, int]:
        """
        Return a human-readable description of this item

        :param int indent: The indentation to prefix
        """
        item = self.item
        value = self.value
        up = self.usage_page
        descr = item
        # Use a prefix to signify attrs that apply to the next input/output
        prefix = " ."
        if item in (
            "Report ID",
            "Usage Minimum",
            "Usage Maximum",
            "Logical Minimum",
            "Physical Minimum",
            "Logical Maximum",
            "Physical Maximum",
            "Report Size",
            "Report Count",
            "Unit Exponent",
        ):
            if item != "Report ID":
                descr = prefix + descr
            descr += f" ({str(value)})"
        elif item == "Collection":
            descr += f" ({HidCollection(value).name.capitalize()})"
            indent += 1
        elif item == "End Collection":
            indent -= 1
        elif item == "Usage Page":
            try:
                descr += f" ({HUT[value].page_name})"
            except KeyError:
                descr += f" (Vendor Usage Page 0x{value:02x})"
        elif item == "Usage":
            usage = value | up
            try:
                descr += f" ({HUT[up >> 16][value]})"
            except KeyError:
                sensor = HUT.usage_page_from_name("Sensor")
                if sensor is not None and (up >> 16) == sensor.page_id:
                    mod = (usage & 0xF000) >> 8
                    usage &= ~0xF000
                    mod_descr = sensor_mods[mod]
                    page_id = (usage & 0xFF00) >> 16
                    try:
                        descr += f" ({HUT[page_id][usage & 0xFF]}  | {mod_descr})"
                    except KeyError:
                        descr += f" (Unknown Usage 0x{value:02x})"
                else:
                    descr += f" (Vendor Usage 0x{value:02x})"
        elif item == "Input" or item == "Output" or item == "Feature":
            descr += " ("
            if value & (0x1 << 0):
                descr += "Cnst,"
            else:
                descr += "Data,"
            if value & (0x1 << 1):
                descr += "Var,"
            else:
                descr += "Arr,"
            if value & (0x1 << 2):
                descr += "Rel"
            else:
                descr += "Abs"
            if value & (0x1 << 3):
                descr += ",Wrap"
            if value & (0x1 << 4):
                descr += ",NonLin"
            if value & (0x1 << 5):
                descr += ",NoPref"
            if value & (0x1 << 6):
                descr += ",Null"
            if value & (0x1 << 7):
                descr += ",Vol"
            if value & (0x1 << 8):
                descr += ",Buff"
            descr += ")"
        elif item == "Unit":
            unit = HidUnit.from_value(value)
            descr += f" ({unit})"
        elif item == "Push":
            pass
        elif item == "Pop":
            pass
        eff_indent = indent
        if item == "Collection":
            eff_indent -= 1
        return " " * eff_indent + descr, indent

    @classmethod
    def _one_item_from_bytes(
        cls: _Type["_HidRDescItem"], rdesc: Union[Bytes, List[U8]]
    ) -> Optional["_HidRDescItem"]:
        """
        Parses a single (the first) item from the given report descriptor.

        :param rdesc: a series of bytes representing the report descriptor

        :returns: a single _HidRDescItem from the first ``item.size`` bytes
                of the descriptor

        .. note:: ``item.index_in_report`` is always 0 when using this function
        """
        idx = 0
        header = rdesc[idx]
        if header == 0 and idx == len(rdesc) - 1:
            # some devices present a trailing 0, skipping it
            return None

        index_in_report = 0  # always zero, oh well
        size = header & 0x3
        if size == 3:
            size = 4
        hid = header & 0xFC
        if hid == 0:
            raise ParseError(f"Unexpected HID type 0 in {header:02x}")

        value = 0
        raw_values = []

        idx += 1
        if size >= 1:
            v = rdesc[idx]
            idx += 1
            raw_values.append(v)
            value |= v
        if size >= 2:
            v = rdesc[idx]
            idx += 1
            raw_values.append(v)
            value |= v << 8
        if size >= 4:
            v = rdesc[idx]
            idx += 1
            raw_values.append(v)
            value |= v << 16
            v = rdesc[idx]
            idx += 1
            raw_values.append(v)
            value |= v << 24

        return _HidRDescItem(index_in_report, hid, value, raw_values)

    @classmethod
    def from_bytes(
        cls: _Type["_HidRDescItem"],
        rdesc: Union[
            Bytes,
            List[U8],
        ],
    ) -> List["_HidRDescItem"]:
        """
        Parses a series of bytes into items.

        :param list rdesc: a series of bytes that are a HID report
                descriptor

        :returns: a list of items representing this report descriptor
        """
        items = []
        idx = 0
        while idx < len(rdesc):
            item = _HidRDescItem._one_item_from_bytes(rdesc[idx:])
            if item is None:
                break
            item.index_in_report = idx
            items.append(item)
            idx += item.size

        return items

    @classmethod
    def from_human_descr(
        cls: _Type["_HidRDescItem"], line: str, usage_page: U16
    ) -> "_HidRDescItem":
        """
        Parses a line from human-readable HID report descriptor e.g.::

            Usage Page (Digitizers)
            Usage (Finger)
            Collection (Logical)
             Report Size (1)
             Report Count (1)
             Logical Minimum (0)
             Logical Maximum (1)
             Usage (Tip Switch)
             Input (Data,Var,Abs)


        :param str line: a single line in the report descriptor
        :param int usage_page: the usage page to set for this item

        :returns: a single item representing the current line
        """
        data = None
        if "(" in line:
            m = re.match(r"\s*(?P<name>[^(]+)\((?P<data>.+)\)", line)
            assert m is not None
            name = m.group("name").strip()
            data = m.group("data")
            if data.lower().startswith("0x"):
                try:
                    data = int(data[2:], 16)
                except ValueError:
                    pass
            else:
                try:
                    data = int(data)
                except ValueError:
                    pass
        # Strip any superfluous stuff from an EndCollection line
        elif "End Collection" in line:
            name = "End Collection"
        else:
            name = line.strip()

        value = None

        def hex_value(string: str, prefix: str) -> Optional[U16]:
            if string.startswith(prefix):
                return int(string[len(prefix) :], 16)
            return None

        if isinstance(data, str):
            if name == "Usage Page":
                up = HUT.usage_page_from_name(data)
                if up is None:
                    prefix = "Vendor Usage Page "
                    assert data.startswith(prefix)
                    value = hex_value(data, prefix)
                else:
                    page = HUT.usage_page_from_name(data)
                    if page is not None:
                        value = page.page_id
                if value is not None:
                    usage_page = value
            elif name == "Usage":
                try:
                    value = HUT[usage_page].from_name[data].usage
                except KeyError:
                    value = hex_value(data, "Vendor Usage ")
                    if value is None:
                        raise
            elif name == "Collection":
                value = HidCollection.from_str(data)
            elif name in "Input Output Feature":
                value = 0
                possible_types = (
                    "Cnst",
                    "Var",
                    "Rel",
                    "Wrap",
                    "NonLin",
                    "NoPref",
                    "Null",
                    "Vol",
                    "Buff",
                )
                for i, t in enumerate(possible_types):
                    if t in data:
                        value |= 0x1 << i
            elif name == "Unit":
                if data == "None":
                    value = 0
                else:
                    value = HidUnit.from_string(data).value
        else:  # data has been converted to an int already
            if name == "Usage Page" and data is not None:
                usage_page = data
            value = data

        v_count = 0
        if value is not None:
            if value <= 0xFF:
                v_count = 1
            elif value <= 0xFFFF:
                v_count = 2
            else:
                v_count = 4
        else:
            value = 0
        tag = hid_items[hid_type[name]][name]

        if value < 0:
            if name == "Unit Exponent":
                value += 16
                value = to_twos_comp(value, v_count * 8)
            elif name in ("Logical Minimum", "Physical Minimum"):
                value = to_twos_comp(value, v_count * 8)

        assert value is not None

        v: U16 = value
        vs = []
        for i in range(v_count):
            vs.append(v & 0xFF)
            v >>= 8

        item = _HidRDescItem(0, tag, value, vs)
        item.usage_page = usage_page << 16

        return item

    def dump_rdesc_kernel(self: "_HidRDescItem", indent: int, dump_file: IO) -> int:
        """
        Write the HID item to the file a C-style format, e.g. ::

            0x05, 0x01,			/* Usage Page (Generic Desktop)			*/

        :param int indent: indentation to prefix
        :param File dump_file: file to write to
        """
        # offset = self.index_in_report
        line = self._get_raw_values()
        line += "\t" * (int((40 - len(line)) / 8))

        descr, indent = self.get_human_descr(indent)

        descr += "\t" * (int((52 - len(descr)) / 8))
        # dump_file.write(f'{line}/* {descr} {str(offset)} */\n')
        dump_file.write(f"\t{line}/* {descr}*/\n")
        return indent

    def dump_rdesc_array(self: "_HidRDescItem", indent: int, dump_file: IO) -> int:
        """
        Format the hid item in hexadecimal format with a
        double-slash comment, e.g. ::

           0x05, 0x01,                    // Usage Page (Generic Desktop)        0

        :param int indent: indentation to prefix
        :param File dump_file: file to write to
        """
        offset = self.index_in_report
        line = self._get_raw_values()

        descr, indent = self.get_human_descr(indent)

        dump_file.write(f"{line:18s} // {offset:03x}:  {descr}\n")
        return indent

    def dump_rdesc_human(self: "_HidRDescItem", indent: int, dump_file: IO) -> int:
        """
        Format the hid item in human-only format e.g. ::

           Usage Page (Generic Desktop)        0

        :param int indent: indentation to prefix
        :param File dump_file: file to write to
        """
        offset = self.index_in_report
        descr, indent = self.get_human_descr(indent)
        descr += " " * (35 - len(descr))
        dump_file.write(f"{descr} {str(offset)}\n")
        return indent


class ReportDescriptor(object):
    """
    Represents a fully parsed HID report descriptor.

    When creating a ``ReportDescriptor`` object,

    - if your source is a stream of bytes, use
      :meth:`from_bytes`
    - if your source is a human-readable descriptor, use
      :meth:`from_human_descr`

    .. attribute:: win8

        ``True`` if the device is Windows8 compatible, ``False`` otherwise

    .. attribute:: input_reports

        All :class:`HidReport` of type ``Input``, addressable by the report ID

    .. attribute:: output_reports

        All :class:`HidReport` of type ``Output``, addressable by the report ID

    .. attribute:: feature_reports

        All :class:`HidReport` of type ``Feature``, addressable by the report ID
    """

    class _Globals(object):
        """
        HID report descriptors uses a stack-based model where some values
        are pushed to the global state and apply to all subsequent items
        until changed or reset.
        """

        def __init__(
            self: "ReportDescriptor._Globals",
            other: Optional["ReportDescriptor._Globals"] = None,
        ) -> None:
            self.usage_page: U16 = 0
            self.logical: Optional[U32] = None
            self.physical: Optional[U32] = None
            self.application: Optional[U32] = None
            self.logical_min: U32 = 0
            self.logical_max: U32 = 0
            self.physical_min: U32 = 0
            self.physical_max: U32 = 0
            self.unit: U32 = 0
            self.unit_exp: U32 = 0
            self.count: int = 0
            self.item_size: int = 0
            if other is not None:
                self.usage_page = other.usage_page
                self.logical = other.logical
                self.physical = other.physical
                self.application = other.application
                self.logical_min = other.logical_min
                self.logical_max = other.logical_max
                self.physical_min = other.physical_min
                self.physical_max = other.physical_max
                self.unit = other.unit
                self.unit = other.unit_exp
                self.count = other.count
                self.item_size = other.item_size

    class _Locals(object):
        """
        HID report descriptors uses a stack-based model where values
        apply until the next Output/InputReport/FeatureReport item.
        """

        def __init__(self: "ReportDescriptor._Locals") -> None:
            self.usages: List[U32] = []
            self.usage_sizes: List[int] = []
            self.usage_min: U32 = 0
            self.usage_max: U32 = 0
            self.usage_max_size: U32 = 0
            self.report_ID: U8 = -1

    def __init__(self: "ReportDescriptor", items: List[_HidRDescItem]) -> None:
        self.input_reports: Dict[U8, HidReport] = {}
        self.feature_reports: Dict[U8, HidReport] = {}
        self.output_reports: Dict[U8, HidReport] = {}
        self.win8: bool = False
        self.rdesc_items = items

        # variables only used during parsing
        self.global_stack: List["ReportDescriptor._Globals"] = []
        self.collection: List[U32] = [0, 0, 0]  # application, physical, logical
        self.local = ReportDescriptor._Locals()
        self.glob: "ReportDescriptor._Globals" = ReportDescriptor._Globals()
        self.current_item = None

        index_in_report = 0
        for item in items:
            item.index_in_report = index_in_report
            index_in_report += item.size
            self._parse_item(item)

        # Drop the parsing-only variables so we don't leak them later
        del self.current_item
        del self.glob
        del self.global_stack
        del self.local
        del self.collection

    def get(
        self: "ReportDescriptor", reportID: U8, reportSize: int
    ) -> Optional[HidReport]:
        """
        Return the input report with the given Report ID or ``None``
        """
        try:
            report = self.input_reports[reportID]
        except KeyError:
            try:
                report = self.input_reports[-1]
            except KeyError:
                return None

        # if the report is larger than it should be, it's OK,
        # extra bytes will just be ignored
        if report.size <= reportSize:
            return report

        return None

    def get_report_from_application(
        self: "ReportDescriptor", application: Union[str, U32]
    ) -> Optional[HidReport]:
        """
        Return the Input report that matches the application or ``None``
        """
        for r in self.input_reports.values():
            if r.application == application or r.application_name == application:
                return r
        return None

    def _get_current_report(self: "ReportDescriptor", type: str) -> HidReport:
        report_lists = {
            "Input": self.input_reports,
            "Output": self.output_reports,
            "Feature": self.feature_reports,
        }
        report_type = {
            "Input": HidReport.Type.INPUT,
            "Output": HidReport.Type.OUTPUT,
            "Feature": HidReport.Type.FEATURE,
        }

        assert type in report_lists

        try:
            cur = report_lists[type][self.local.report_ID]
        except KeyError:
            cur = HidReport(
                self.local.report_ID, self.glob.application, report_type[type]  # type: ignore
            )
            report_lists[type][self.local.report_ID] = cur
        return cur

    def _concatenate_usages(self: "ReportDescriptor") -> None:
        if self.local.usage_max and self.local.usage_max_size <= 2:
            if self.local.usage_max & 0xFFFF0000 != self.glob.usage_page:
                self.local.usage_max &= 0xFFFF
                self.local.usage_max |= self.glob.usage_page
                self.local.usage_min &= 0xFFFF
                self.local.usage_min |= self.glob.usage_page

        for i, v in reversed(list(enumerate(self.local.usages))):
            if self.local.usage_sizes[i] > 2:
                continue
            if v & 0xFFFF0000 == self.glob.usage_page:
                break
            self.local.usages[i] = v & 0xFFFF | self.glob.usage_page

    def _parse_item(self: "ReportDescriptor", rdesc_item: _HidRDescItem) -> None:
        # store current usage_page in rdesc_item
        rdesc_item.usage_page = self.glob.usage_page
        item = rdesc_item.item
        value = rdesc_item.value
        size = rdesc_item.size - 1

        if item == "Report ID":
            self.local.report_ID = value
        elif item == "Push":
            self.global_stack.append(self.glob)
            self.glob = ReportDescriptor._Globals(self.glob)
        elif item == "Pop":
            self.glob = self.global_stack.pop()
        elif item == "Usage Page":
            self.glob.usage_page = value << 16
        elif item == "Collection":
            self._concatenate_usages()

            c = HidCollection(value)
            try:
                if c.type == HidCollection.Type.PHYSICAL:
                    self.collection[1] += 1
                    self.glob.physical = self.local.usages[-1]
                elif c.type == HidCollection.Type.APPLICATION:
                    self.collection[0] += 1
                    self.glob.application = self.local.usages[-1]
                elif c.type == HidCollection.Type.LOGICAL:
                    self.collection[2] += 1
                    self.glob.logical = self.local.usages[-1]
            except IndexError:
                pass
            # reset the usage list
            self.local.usages = []
            self.local.usage_sizes = []
            self.local.usage_min = 0
            self.local.usage_max = 0
            self.local.usage_max_size = 0
        elif item == "Usage Minimum":
            if size <= 2:
                self.local.usage_min = value | self.glob.usage_page
            else:
                self.local.usage_min = value
        elif item == "Usage Maximum":
            if size <= 2:
                self.local.usage_max = value | self.glob.usage_page
            else:
                self.local.usage_max = value
            self.local.usage_max_size = size
        elif item == "Logical Minimum":
            self.glob.logical_min = value
        elif item == "Logical Maximum":
            self.glob.logical_max = value
        elif item == "Physical Minimum":
            self.glob.physical_min = value
        elif item == "Physical Maximum":
            self.glob.physical_max = value
        elif item == "Unit":
            self.glob.unit = value
        elif item == "Unit Exponent":
            self.glob.unit_exp = value
        elif item == "Usage":
            if size <= 2:
                self.local.usages.append(value | self.glob.usage_page)
            else:
                self.local.usages.append(value)
            self.local.usage_sizes.append(size)
        elif item == "Report Count":
            self.glob.count = value
        elif item == "Report Size":
            self.glob.item_size = value
        elif item in ("Input", "Feature", "Output"):
            self.current_input_report = self._get_current_report(item)

            self._concatenate_usages()

            inputItems = HidField.getHidFields(
                self.local.report_ID,
                self.glob.logical,
                self.glob.physical,
                self.glob.application,
                cast(Tuple[U32, U32, U32], tuple(self.collection)),
                value,
                self.glob.usage_page,
                self.local.usages,
                self.local.usage_min,
                self.local.usage_max,
                self.glob.logical_min,
                self.glob.logical_max,
                self.glob.physical_min,
                self.glob.physical_max,
                self.glob.unit,
                self.glob.unit_exp,
                self.glob.item_size,
                self.glob.count,
            )
            self.current_input_report.extend(inputItems)
            if (
                item == "Feature"
                and len(self.local.usages) > 0
                and self.local.usages[-1] == 0xFF0000C5
            ):
                self.win8 = True
            self.local.usages = []
            self.local.usage_sizes = []
            self.local.usage_min = 0
            self.local.usage_max = 0
            self.local.usage_max_size = 0

    def dump(
        self: "ReportDescriptor", dump_file=sys.stdout, output_type="default"
    ) -> None:
        """
        Write this ReportDescriptor into the given file

        The "default" format prints each item as hexadecimal format with a
        double-slash comment, e.g. ::

           0x05, 0x01,                    // Usage Page (Generic Desktop)        0
           0x09, 0x02,                    // Usage (Mouse)                       2


        The "kernel" format prints each item in valid C format, for easy
        copy-paste into a kernel or C source file: ::

               0x05, 0x01,         /* Usage Page (Generic Desktop)         */
               0x09, 0x02,         /* Usage (Mouse)                        */

        :param File dump_file: the file to write to
        :param str output_type: the output format, one of "default" or "kernel"
        """
        assert output_type in ["default", "kernel", "human"]

        indent = 0
        for rdesc_item in self.rdesc_items:
            if output_type == "default":
                indent = rdesc_item.dump_rdesc_array(indent, dump_file)
            elif output_type == "kernel":
                indent = rdesc_item.dump_rdesc_kernel(indent, dump_file)
            elif output_type == "human":
                indent = rdesc_item.dump_rdesc_human(indent, dump_file)

    @property
    def size(self: "ReportDescriptor") -> int:
        """
        Returns the size of the report descriptor in bytes.
        """
        return sum([item.size for item in self.rdesc_items])

    @property
    def bytes(self: "ReportDescriptor") -> List[U8]:
        """
        This report descriptor as a list of 8-bit integers.
        """
        data = []
        for item in self.rdesc_items:
            data.extend(item.bytes)
        return data

    @classmethod
    def from_bytes(
        cls: _Type["ReportDescriptor"], rdesc: Union[Bytes, List[U8]]
    ) -> "ReportDescriptor":
        """
        Parse the given list of 8-bit integers.

        :param list rdesc: a list of bytes that are this report descriptor
        """
        items = _HidRDescItem.from_bytes(rdesc)

        return ReportDescriptor(items)

    @classmethod
    def from_string(cls: _Type["ReportDescriptor"], rdesc: str) -> "ReportDescriptor":
        """
        Parse a string in the format of series of hex numbers::

           12 34 ab cd ...

        and the first number in that series is the count of bytes, excluding
        that first number. This is the format returned by your
        ``/dev/hidraw`` event node, so just pass it along.


        :param list rdesc: a string that represents the list of bytes
        """

        irdesc = [int(r, 16) for r in rdesc.split()[1:]]
        items = _HidRDescItem.from_bytes(irdesc)

        return ReportDescriptor(items)

    @classmethod
    def from_human_descr(
        cls: _Type["ReportDescriptor"], rdesc_str: str
    ) -> "ReportDescriptor":
        """
        Parse the given human-readable report descriptor, e.g. ::

            Usage Page (Digitizers)
            Usage (Finger)
            Collection (Logical)
             Report Size (1)
             Report Count (1)
             Logical Minimum (0)
             Logical Maximum (1)
             Usage (Tip Switch)
             Input (Data,Var,Abs)
             Report Size (7)
             Logical Maximum (127)
             Input (Cnst,Var,Abs)
             Report Size (8)
             Logical Maximum (255)
             Usage (Contact Id)

        """
        usage_page = 0
        items = []
        for line in rdesc_str.splitlines():
            line = line.strip()
            if not line:
                continue
            item = _HidRDescItem.from_human_descr(line, usage_page)
            usage_page = item.usage_page >> 16
            items.append(item)

        return ReportDescriptor(items)


def get_descriptor(fd: int):
    from hhd.controller.lib.ioctl import HIDIOCGRDESC, HIDIOCGRDESCSIZE
    from fcntl import ioctl
    import ctypes

    size = ctypes.c_int32()
    ioctl(fd, HIDIOCGRDESCSIZE, size)
    c_mask = ctypes.create_string_buffer(4096+4)
    c_mask[:4] = size.value.to_bytes(4, byteorder=sys.byteorder)
    ioctl(fd, HIDIOCGRDESC, c_mask)
    rdesc = c_mask.raw
    return rdesc[4:size.value+4]

def print_descriptor(fd: int, format: str = 'default'):
    desc = get_descriptor(fd)
    return ReportDescriptor.from_bytes(desc).dump(output_type=format)
