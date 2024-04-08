import copy
import os
from gettext import GNUTranslations, find
from typing import Mapping, Sequence, cast

from hhd.plugins import Config, HHDLocale, HHDSettings

_translations = {}


def translate_ver(conf: Config, lang: str | None = None):
    v = conf.get("version", "")

    if not lang:
        lang = conf.get("hhd.settings.language", "")
    return v + "-" + lang


def get_mo_files(conf: Config, locales: Sequence[HHDLocale], lang: str | None = None):
    if not lang:
        lang = conf.get("hhd.settings.language", "")
    if lang and lang != "system":
        languages = [lang]
    else:
        languages = None

    fns = []
    for locale in locales:
        fns.extend(find(locale["domain"], locale["dir"], languages, all=True))
    return fns


def translation(conf: Config, locales: Sequence[HHDLocale], lang: str | None = None):
    mofiles = get_mo_files(conf, locales, lang)
    result = None
    for mofile in mofiles:
        key = (GNUTranslations, os.path.abspath(mofile))
        t = _translations.get(key)
        if t is None:
            with open(mofile, "rb") as fp:
                t = _translations.setdefault(key, GNUTranslations(fp))

        t = copy.copy(t)
        if result is None:
            result = t
        else:
            result.add_fallback(t)
    return result


def trn_dict(d: Mapping, trn: GNUTranslations):
    out = dict(d)
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = trn_dict(v, trn)
        elif isinstance(v, str):
            out[k] = trn.gettext(v)
        elif isinstance(v, list):
            out[k] = [trn.gettext(l) if isinstance(l, str) else l for l in v]
        else:
            out[k] = v
    return out


def translate(
    d: Mapping, conf: Config, locales: Sequence[HHDLocale], lang: str | None = None
):
    trn = translation(conf, locales, lang)
    base = d
    if trn:
        base = trn_dict(base, trn)
    return base