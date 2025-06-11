import copy
import os
import subprocess
from gettext import GNUTranslations, find
from typing import Mapping, Sequence, cast

from hhd.plugins import Config, Context, HHDLocale, HHDSettings

_translations = {}


def get_user_lang(ctx: Context):
    if not ctx:
        return None
    try:
        out = subprocess.check_output(
            ["sh", "-l", "-c", "locale"],
            env={},
            user=ctx.euid,
            group=ctx.egid,
        )
        for ln in out.decode().split("\n"):
            if "LANG" in ln:
                return ln.strip().split("=")[-1]
        # Alternative:
        # return subprocess.check_output(
        #     ["sh", "-l", "-c", "echo $LANG"],
        #     env={},
        #     user=ctx.euid,
        #     group=ctx.egid,
        # ).decode()
    except Exception:
        return None


def translate_ver(conf: Config, lang: str | None = None, user_lang: str | None = None):
    v = conf.get("version", "")

    if not lang:
        lang = conf.get("hhd.settings.language", "")
    if lang == "system" and user_lang:
        lang = user_lang
    return v + "-" + lang


def get_mo_files(
    conf: Config,
    locales: Sequence[HHDLocale],
    lang: str | None = None,
    user_lang: str | None = None,
):
    if not lang:
        lang = conf.get("hhd.settings.language", "")
    if lang == "system" and user_lang:
        lang = user_lang
    if lang and lang != "system":
        languages = [lang]
    else:
        languages = None

    fns = []
    for locale in locales:
        fns.extend(find(locale["domain"], locale["dir"], languages, all=True))
    return fns


def translation(
    conf: Config,
    locales: Sequence[HHDLocale],
    lang: str | None = None,
    user_lang: str | None = None,
):
    mofiles = get_mo_files(conf, locales, lang, user_lang)
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
        elif isinstance(v, str) and v:
            out[k] = trn.gettext(v)
        elif isinstance(v, list):
            out[k] = [trn.gettext(l) if l and isinstance(l, str) else l for l in v]
        else:
            out[k] = v
    return out


def translate(
    d: Mapping,
    conf: Config,
    locales: Sequence[HHDLocale],
    lang: str | None = None,
    user_lang: str | None = None,
):
    trn = translation(conf, locales, lang, user_lang)
    base = d
    if trn:
        base = trn_dict(base, trn)
    return base
