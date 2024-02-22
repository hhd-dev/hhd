from copy import deepcopy
from threading import Lock
from typing import (
    Any,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
    TypeVar,
    cast,
)

Pytree = int | float | str | Sequence["Pytree"] | Mapping[str, "Pytree"]
A = TypeVar("A")


def parse_conf(c: Pytree, out: MutableMapping | None = None):
    if not isinstance(c, MutableMapping):
        return c

    if out is None:
        out = {}

    for multival, v in c.items():
        d = out
        subs = multival.split(".")
        for k in subs[:-1]:
            d[k] = d.get(k, {})
            d = d[k]

        if subs[-1] not in d or (
            not isinstance(d[subs[-1]], Mapping) or not isinstance(v, Mapping)
        ):
            d[subs[-1]] = parse_conf(v)
        else:
            mout = {}
            parse_conf(d[subs[-1]], mout)
            parse_conf(v, mout)
            d[subs[-1]] = mout

    return out


def parse_confs(
    confs: Sequence[Pytree], out: MutableMapping | Pytree | None = None
) -> MutableMapping | Pytree:
    if not isinstance(out, MutableMapping):
        out = {}
    for c in confs:
        if not isinstance(out, MutableMapping):
            out = {}
        if isinstance(c, Mapping):
            parse_conf(c, out)
        else:
            out = c
    return out


def to_seq(key: str | tuple[str, ...]):
    if isinstance(key, str):
        key = (key,)

    seq = []
    for k in key:
        for s in k.split("."):
            seq.append(s)
    return seq


def compare_dicts(a, b):
    if len(a) != len(b):
        return False

    for k in a:
        if not k in b:
            return False

        if isinstance(a[k], Mapping) and isinstance(b[k], Mapping):
            if not compare_dicts(a[k], b[k]):
                return False
        else:
            if not a[k] == b[k]:
                return False

    return True


class Config:
    def __init__(
        self, conf: Pytree | Sequence[Pytree] = [], readonly: bool = False
    ) -> None:
        self._conf: Pytree | MutableMapping = {}
        self._lock = Lock()
        self._updated = False
        self.readonly = readonly
        self.update(conf)
        self.updated = False

    def update(self, conf: Pytree | Sequence[Pytree]):
        with self._lock:
            conf = deepcopy(conf)
            if isinstance(conf, Sequence):
                self._conf = parse_confs(conf, self._conf)
            else:
                if isinstance(self._conf, MutableMapping):
                    parse_conf(conf, self._conf)
                else:
                    self._conf = conf
        self.updated = True

    def __eq__(self, __value: object) -> bool:
        if not isinstance(__value, Config):
            return False

        if __value is self:
            return True

        with __value._lock, self._lock:
            return compare_dicts(__value._conf, self._conf)

    def __setitem__(self, key: str | tuple[str, ...], val):
        with self._lock:
            val = deepcopy(val)
            seq = to_seq(key)

            cont = {}
            d = cont
            for s in seq[:-1]:
                d[s] = {}
                d = d[s]

            d[seq[-1]] = val
            if isinstance(self._conf, MutableMapping):
                init = deepcopy(self._conf)
                parse_conf(cont, self._conf)
                # FIXME: verify no regressions
                if init != self._conf:
                    self._updated = True
            else:
                self._conf = cont
                if self._conf != cont:
                    self._updated = True

    def __contains__(self, key: str | tuple[str, ...]):
        with self._lock:
            seq = to_seq(key)
            d = self._conf
            for s in seq:
                if s not in d:
                    return False
                d = cast(Mapping, d)[s]
        return True

    def __getitem__(self, key: str | tuple[str, ...]) -> "Config":
        with self._lock:
            assert isinstance(self._conf, MutableMapping)
            seq = to_seq(key)
            d = self._conf
            for s in seq:
                d = cast(Mapping, d)[s]
            return Config([deepcopy(d)])

    def __delitem__(self, key: str | tuple[str, ...]):
        with self._lock:
            assert isinstance(self._conf, MutableMapping)
            seq = to_seq(key)
            d = self._conf
            for s in seq[:-1]:
                d = cast(Mapping, d)[s]
            del d[seq[-1]]
        self.updated = True

    def get(self, key, default: A) -> A:
        try:
            return self[key].to(type(default))
        except KeyError:
            return default

    def to(self, t: type[A]) -> A:
        return cast(t, self.conf)

    def copy(self):
        return Config([self.conf])

    @property
    def conf(self):
        with self._lock:
            return deepcopy(self._conf)

    @property
    def updated(self):
        with self._lock:
            return self._updated

    @updated.setter
    def updated(self, v: bool):
        with self._lock:
            self._updated = v
