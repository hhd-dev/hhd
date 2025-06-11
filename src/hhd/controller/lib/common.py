import re
from typing import Literal, NamedTuple, Sequence


class BM(NamedTuple):
    loc: int
    flipped: bool = False


NumType = Literal["u32", "i32", "m32", "u16", "i16", "m16", "u8", "i8", "m8"]
"""Numerical type for axis.

Number is bit length. Letter signifies sign.
 - `u`: unsigned
 - 'i': signed
 - 'm': signed with middle point. Essentially, if `d` is bit width, `out = in - (1 << d)`
 """


class AM(NamedTuple):
    loc: int
    type: NumType
    order: Literal["little", "big"] = "little"
    scale: float | None = None
    offset: float = 0
    flipped: bool = False
    bounds: tuple[int, int] | None = None


class CM(NamedTuple):
    loc: int
    type: NumType | Literal["bit"]
    order: Literal["little", "big"] = "little"
    scale: float | None = None
    offset: float = 0
    bounds: tuple[int, int] | None = None
    flipped: bool = False


def decode_axis(buff: bytes, t: AM):
    match t.type:
        case "i32":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 4], t.order, signed=True
            )
            s = (1 << 31) - 1
        case "u32":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 4], t.order, signed=False
            )
            s = (1 << 32) - 1
        case "m32":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 4], t.order, signed=False
            ) - (1 << 31)
            s = (1 << 31) - 1
        case "i16":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 2], t.order, signed=True
            )
            s = (1 << 15) - 1
        case "u16":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 2], t.order, signed=False
            )
            s = (1 << 16) - 1
        case "m16":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 2], t.order, signed=False
            ) - (1 << 15)
            s = (1 << 15) - 1
        case "i8":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 1], t.order, signed=True
            )
            s = (1 << 7) - 1
        case "u8":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 1], t.order, signed=False
            )
            s = (1 << 8) - 1
        case "m8":
            o = int.from_bytes(
                buff[t.loc >> 3 : (t.loc >> 3) + 1], t.order, signed=False
            ) - (1 << 7)
            s = (1 << 7)
        case _:
            assert False, f"Invalid formatting {t.type}."

    if t.scale:
        v = t.scale * o + t.offset
    else:
        v = o / s + t.offset

    if t.flipped:
        return -v
    else:
        return v


def encode_axis(buff: bytearray, t: AM, val: float):
    if t.flipped:
        val = -val

    if t.scale:
        new_val = int(t.scale * val + t.offset)
        if t.bounds:
            new_val = min(max(new_val, t.bounds[0]), t.bounds[1])
    else:
        new_val = None

    match t.type:
        case "i32":
            if not new_val:
                new_val = int(((1 << 31) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 4] = int.to_bytes(
                new_val, 4, t.order, signed=True
            )
        case "u32":
            if not new_val:
                new_val = int(((1 << 32) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 4] = int.to_bytes(
                new_val, 4, t.order, signed=False
            )
        case "m32":
            if not new_val:
                new_val = int(round(((1 << 31) - 1) * val + (1 << 31) - 1))
            buff[t.loc >> 3 : (t.loc >> 3) + 4] = int.to_bytes(
                new_val, 4, t.order, signed=False
            )
        case "i16":
            if not new_val:
                new_val = int(((1 << 15) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 2] = int.to_bytes(
                new_val, 2, t.order, signed=True
            )
        case "u16":
            if not new_val:
                new_val = int(((1 << 16) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 2] = int.to_bytes(
                new_val, 2, t.order, signed=False
            )
        case "m16":
            if not new_val:
                new_val = int(round(((1 << 15) - 1) * val + (1 << 15) - 1))
            buff[t.loc >> 3 : (t.loc >> 3) + 2] = int.to_bytes(
                new_val, 2, t.order, signed=False
            )
        case "i8":
            if not new_val:
                new_val = int(((1 << 7) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 1] = int.to_bytes(
                new_val, 1, t.order, signed=True
            )
        case "u8":
            if not new_val:
                new_val = int(((1 << 8) - 1) * val)
            buff[t.loc >> 3 : (t.loc >> 3) + 1] = int.to_bytes(
                new_val, 1, t.order, signed=False
            )
        case "m8":
            if not new_val:
                new_val = int(round(((1 << 7) - 1) * val + (1 << 7) - 1))
            buff[t.loc >> 3 : (t.loc >> 3) + 1] = int.to_bytes(
                new_val, 1, t.order, signed=False
            )
        case _:
            assert False, f"Invalid formatting {t.type}."


def hexify(d: int | Sequence[int]):
    if isinstance(d, int):
        return f"{d:04x}"
    else:
        return [hexify(v) for v in d]


def pretty_print(dev: dict[str, str | int | bytes]):
    out = ""
    for n, v in dev.items():
        if isinstance(v, int):
            out += f"{n}: {hexify(v)}\n"
        elif isinstance(v, str):
            out += f"{n}: '{v}'\n"
        else:
            out += f"{n}: {v}\n"
    return out


def get_button(rep: bytes, map: BM):
    v = bool(rep[map.loc // 8] & (1 << (7 - (map.loc % 8))))
    if map.flipped:
        return not v
    return v


def set_button(rep: bytearray, map: BM, val: bool):
    if (val and not map.flipped) or (not val and map.flipped):
        rep[map.loc // 8] |= 1 << (7 - (map.loc % 8))
    else:
        rep[map.loc // 8] &= 255 - (1 << (7 - (map.loc % 8)))


def decode_config(rep: bytes, map: CM):
    if map.type == "bit":
        return get_button(rep, BM(map.loc, map.flipped))

    ax = decode_axis(rep, AM(map.loc, map.type, map.order, map.scale, map.offset))
    if map.bounds:
        return min(max(ax, map.bounds[0]), map.bounds[1])
    else:
        return ax


def matches_patterns(val: str | int, pats: Sequence[int | str | re.Pattern]):
    if not pats:
        return True

    for p in pats:
        if isinstance(p, re.Pattern):
            assert isinstance(val, str), f"Attempted regex pattern match on val {p}."
            if p.match(val):
                return True
        else:
            if p == val:
                return True
    return False
