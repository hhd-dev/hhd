from copy import deepcopy
from typing import Any, Mapping, MutableMapping, MutableSequence, Sequence

Pytree = int | float | str | Sequence["Pytree"] | Mapping[str, "Pytree"]


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


def parse_confs(confs: Sequence[Pytree], out: MutableMapping | None = None):
    if out is None:
        out = {}
    for c in confs:
        parse_conf(c, out)
    return out


def to_seq(key: str | tuple[str, ...]):
    if isinstance(key, str):
        key = (key,)

    seq = []
    for k in key:
        for s in k.split("."):
            seq.append(s)
    return seq


class Config:
    def __init__(
        self, conf: Pytree | Sequence[Pytree] = [], readonly: bool = False
    ) -> None:
        self.conf = {}
        self.update(conf)
        self.updated = False
        self.readonly = readonly

    def update(self, conf: Pytree | Sequence[Pytree]):
        conf = deepcopy(conf)
        if isinstance(conf, Sequence):
            parse_confs(conf, self.conf)
        else:
            parse_conf(conf, self.conf)
        self.updated = True

    def __setitem__(self, key: str | tuple[str, ...], val):
        val = deepcopy(val)
        seq = to_seq(key)

        cont = {}
        d = cont
        for s in seq[:-1]:
            d[s] = {}
            d = d[s]

        d[seq[-1]] = val
        parse_conf(cont, self.conf)
        self.updated = True

    def __getitem__(self, key: str | tuple[str, ...]):
        seq = to_seq(key)
        d = self.conf
        for s in seq:
            d = d[s]
        return d

    def get(self, key, default):
        try:
            return self.__getitem__(key)
        except KeyError as e:
            return default
