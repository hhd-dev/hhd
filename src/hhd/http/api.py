import itertools
import json
import logging
import os
import socket
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn, TCPServer
from threading import Condition, Thread
from typing import Any, Mapping, Sequence, cast
from urllib.parse import parse_qs, urlparse

from hhd.plugins import (
    Config,
    Context,
    Emitter,
    HHDLocale,
    HHDSettings,
    get_relative_fn,
    load_relative_yaml,
)

from .i18n import get_user_lang, translate, translate_ver

logger = logging.getLogger(__name__)


def sanitize_name(n: str):
    import re

    return re.sub(r"[^ a-zA-Z0-9]+", "", n)


def sanitize_fn(n: str):
    import re

    return re.sub(r"[^ a-zA-Z0-9\._/]+", "", n)


STANDARD_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS, DELETE",
    "Access-Control-Allow-Headers": "*",
    # "Access-Control-Expose-Headers": "*, Version",
    "Access-Control-Max-Age": "86400",
    "WWW-Authenticate": "Bearer",
}

ERROR_HEADERS = {**STANDARD_HEADERS, "Content-type": "text/plain"}
AUTH_HEADERS = ERROR_HEADERS
OK_HEADERS = {**STANDARD_HEADERS, "Content-type": "application/json"}

# https://en.wikipedia.org/wiki/List_of_Unicode_characters#Control_codes
_control_char_table = str.maketrans(
    {c: rf"\x{c:02x}" for c in itertools.chain(range(0x20), range(0x7F, 0xA0))}
)
_control_char_table[ord("\\")] = r"\\"

SECTIONS = load_relative_yaml("../sections.yml")["sections"]


def parse_path(path: str) -> tuple[list, dict[str, list[str]]]:
    try:
        url = urlparse(path)
        if url.path:
            segments = url.path[1:].split("/")
        else:
            segments = []

        params = {
            k: v for k, v in parse_qs(url.query, keep_blank_values=True).items() if v
        }
        return segments, params
    except Exception:
        return [], {}


class RestHandler(BaseHTTPRequestHandler):
    settings: HHDSettings
    cond: Condition
    conf: Config
    info: Config
    profiles: Mapping[str, Config]
    emit: Emitter
    locales: Sequence[HHDLocale]
    ctx: Context
    user_lang: str | None
    token: str | None

    def set_response(self, code: int, headers: dict[str, str] = {}):
        # Allow skipping CORS by responding with specific origin
        if og := self.headers.get("Origin", None):
            headers = {**headers, "Access-Control-Allow-Origin": og}
        self.send_response(code)
        for title, head in headers.items():
            self.send_header(title, head)
        self.end_headers()

    def do_OPTIONS(self):
        self.set_response(
            204,
            STANDARD_HEADERS,
        )

    def is_authenticated(self):
        if not self.token:
            return True

        auth = self.headers["Authorization"]
        if not auth:
            return False

        if not isinstance(auth, str):
            return False

        if not auth.lower().startswith("bearer "):
            return False

        return auth.lower()[len("Bearer ") :] == self.token

    def send_authenticate(self):
        if self.is_authenticated():
            return True

        self.set_response(401, {"Content-type": "text/plain"})
        self.wfile.write(
            f"Handheld Daemon Error: Authentication is on and you did not supply the proper bearer token.".encode()
        )

        return False

    def send_json(self, data: Any):
        self.set_response_ok()
        self.wfile.write(json.dumps(data).encode())

    def set_response_ok(self, extra_headers={}):
        self.set_response(200, {**OK_HEADERS, **extra_headers})

    def send_not_found(self, error: str):
        self.set_response(404, ERROR_HEADERS)
        self.wfile.write(b"Handheld Daemon Error (404, invalid endpoint):\n")
        self.wfile.write(error.encode())

    def send_error_str(self, error: str):
        self.set_response(400, ERROR_HEADERS)
        self.wfile.write(b"Handheld Daemon Error:\n")
        self.wfile.write(error.encode())

    def send_error(self, *args, **kwargs):
        if len(args) == 1:
            return self.send_error_str(args[0])
        else:
            for title, head in STANDARD_HEADERS.items():
                self.send_header(title, head)
            return super().send_error(*args, **kwargs)

    def send_file(self, fn: str):
        if not "." in fn:
            return self.send_error(f"Invalid file: {fn}")
        match fn[fn.rindex(".") :]:
            case ".css":
                ctype = "text/css"
            case ".js":
                ctype = "application/javascript"
            case ".html" | ".htm" | ".php":
                ctype = "text/html"
            case other:
                return self.send_error(f"File type '{other} of '{fn}' not supported.")
        self.set_response(200, {**STANDARD_HEADERS, "Content-type": ctype})
        with open(get_relative_fn(fn), "rb") as f:
            self.wfile.write(f.read())

    def handle_profile(
        self, segments: list[str], params: dict[str, list[str]], content: Any | None
    ):
        if not segments:
            return self.send_not_found(
                f"No endpoint provided for '/profile/...', (e.g., list, get, set, apply)"
            )

        with self.cond:
            match segments[0]:
                case "list":
                    self.send_json(list(self.profiles))
                case "get":
                    if "profile" not in params:
                        return self.send_error(f"Profile not specified")
                    profile = sanitize_name(params["profile"][0])
                    if profile not in self.profiles:
                        return self.send_error(f"Profile '{profile}' not found.")
                    self.send_json(self.profiles[profile].conf)
                case "set":
                    if "profile" not in params:
                        return self.send_error(f"Profile not specified")
                    if not content or not isinstance(content, Mapping):
                        return self.send_error(f"Data for the profile not sent.")

                    profile = sanitize_name(params["profile"][0])
                    self.emit(
                        {"type": "profile", "name": profile, "config": Config(content)}
                    )
                    # Wait for the profile to be processed
                    self.cond.wait()

                    # Return the profile
                    if profile in self.profiles:
                        self.send_json(self.profiles[profile].conf)
                    else:
                        self.send_error(f"Applied profile not found (race condition?).")
                case "del":
                    if "profile" not in params:
                        return self.send_error(f"Profile not specified")

                    profile = sanitize_name(params["profile"][0])
                    if profile not in self.profiles:
                        return self.send_error(f"Profile '{profile}' not found.")
                    self.emit({"type": "profile", "name": profile, "config": None})
                    # Wait for the profile to be processed
                    self.cond.wait()

                    if profile in self.profiles:
                        self.send_error(f"Applied profile not found (race condition?).")
                    else:
                        self.set_response_ok()
                case "apply":
                    if "profile" not in params:
                        return self.send_error(f"Profile not specified")

                    profiles = [sanitize_name(p) for p in params["profile"]]
                    for p in profiles:
                        if p not in self.profiles:
                            return self.send_error(f"Profile '{p}' not found.")

                    self.emit([{"type": "apply", "name": p} for p in profiles])
                    # Wait for the profile to be processed
                    self.cond.wait()
                    # Return the profile
                    self.send_json(self.conf.conf)
                case other:
                    self.send_not_found(f"Command 'profile/{other}' not supported.")

    def handle_image(
        self, segments: list[str], params: dict[str, list[str]], content: Any | None
    ):
        if len(segments) < 2:
            return self.send_not_found(
                "Image data not provided. Syntax: /api/v1/image/{game}/{type}"
            )

        game = segments[0]
        image_type = segments[1]

        img = self.emit.get_image(game, image_type)
        if img is None:
            return self.send_error(f"Image '{game}/{image_type}' not found.")

        if img.endswith(".jpg") or img.endswith(".jpeg"):
            ctype = "image/jpeg"
        elif img.endswith(".png"):
            ctype = "image/png"
        else:
            return self.send_error(f"Image type '{img}' not supported.")

        if not os.path.exists(img):
            return self.send_error(f"Image '{img}' not found.")

        self.set_response_ok(extra_headers={"Content-type": ctype})
        with open(img, "rb") as f:
            self.wfile.write(f.read())

    def v1_endpoint(self, content: Any | None):
        segments, params = parse_path(self.path)
        langs = params.get("lang", params.get("locale", None))
        lang = langs[0] if langs else None

        if not segments:
            return self.send_not_found(f"Empty path.")

        if segments[0] != "api":
            return self.send_not_found(
                f"Only the API endpoint ('/api/v1') is supported for now."
            )

        if len(segments) < 2 or segments[1] != "v1":
            return self.send_not_found(
                f"Only v1 endpoint is supported by this version of hhd ('/api/v1')."
            )

        if len(segments) == 2:
            return self.send_not_found(f"No command provided")

        command = segments[2].lower()
        match command:
            case "image" | "images":
                self.handle_image(segments[3:], params, content)
            case "profile":
                self.handle_profile(segments[3:], params, content)
            case "settings":
                v = translate_ver(self.conf, lang=lang, user_lang=self.user_lang)
                self.set_response_ok({"Version": v})
                with self.cond:
                    s = dict(deepcopy(self.settings))
                    try:
                        s["hhd"]["version"] = {  # type: ignore
                            "type": "version",
                            "tags": ["non-essential", "advanced", "expert", "hide"],
                            "value": v,
                        }
                    except Exception as e:
                        logger.error(f"Error while writing version hash to response.")
                    s = translate(
                        s, self.conf, self.locales, lang=lang, user_lang=self.user_lang
                    )
                    self.wfile.write(json.dumps(s).encode())
            case "state":
                self.set_response_ok()
                with self.cond:
                    if content:
                        if not isinstance(content, Mapping):
                            return self.send_error(
                                f"State content should be a dictionary."
                            )
                        self.emit({"type": "state", "config": Config(content)})
                        self.cond.wait()
                    elif "poll" in params:
                        # Hang for the next update if the UI requests it.
                        self.cond.wait()
                    out = {**cast(dict, self.conf.conf), "info": self.info.conf}
                    out["version"] = translate_ver(
                        self.conf, lang=lang, user_lang=self.user_lang
                    )
                    out = translate(
                        out,
                        self.conf,
                        self.locales,
                        lang=lang,
                        user_lang=self.user_lang,
                    )
                    self.wfile.write(json.dumps(out).encode())
            case "version":
                self.send_json({"version": 5})
            case "sections":
                self.send_json(
                    translate(
                        SECTIONS,
                        self.conf,
                        self.locales,
                        lang=lang,
                        user_lang=self.user_lang,
                    )
                )
            case other:
                self.send_not_found(f"Command '{other}' not supported.")

    def do_GET(self):
        # Danger zone unauthenticated
        # Be very careful
        try:
            path = sanitize_fn(urlparse(self.path).path)
            if path.startswith("/"):
                path = path[1:]
            match path.split("/"):
                case ["" | "index.html" | "index.php"]:
                    return self.send_file("./index.html")
                case ["static", *other]:
                    return self.send_file(os.path.join("static", *other))
                case ["api", *other]:
                    if not self.send_authenticate():
                        return
                    self.v1_endpoint(None)
                case other:
                    return self.send_not_found(f"File not found:\n{path}")
        except Exception as e:
            logger.debug(f"Encountered error while serving unauthenticated request.")
            try:
                return self.send_error(f"Encountered error while serving request:\n{e}")
            except Exception:
                # Generated due to polling website going in the background
                pass

    def do_POST(self):
        if not self.send_authenticate():
            return

        content_length = int(self.headers["Content-Length"])
        content = self.rfile.read(content_length)
        try:
            content_json = json.loads(content)
        except Exception as e:
            return self.send_error(
                f"Parsing the POST content as json failed with the following error:\n{e}"
            )
        self.v1_endpoint(content_json)

    def log_message(self, format: str, *args: Any) -> None:
        message = format % args
        logger.error(
            f"Received invalid request from '{self.address_string()}':\n{message.translate(_control_char_table)}"
        )

    def log_request(self, code="-", size="-"):
        pass

    def __getattr__(self, val: str):
        if not val.startswith("do_"):
            raise AttributeError()

        logger.warning(
            f"Received request type '{val[3:].translate(_control_char_table)}' from '{self.address_string()}'. Handling as GET."
        )
        return self.do_GET


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


class UnixHTTPServer(ThreadingMixIn, TCPServer):
    address_family = socket.AF_UNIX


class HHDHTTPServer:
    def __init__(
        self,
        localhost: bool,
        port: int,
        token: str | None,
    ) -> None:
        self.localhost = localhost
        self.port = port
        cond = Condition()

        # Have to subclass to create closure
        class NewRestHandler(RestHandler):
            pass

        NewRestHandler.cond = cond
        NewRestHandler.token = token
        self.handler = NewRestHandler

        # Use another class for Unix handler without
        # authentication since the file is root only
        class NewUnixHandler(RestHandler):
            pass

        NewUnixHandler.cond = cond
        NewUnixHandler.token = None
        self.uhandler = NewUnixHandler

        self.cond = cond
        self.https = None
        self.t = None
        self.unix = None
        self.tu = None

    def update(
        self,
        settings: HHDSettings,
        conf: Config,
        info: Config,
        profiles: Mapping[str, Config],
        emit: Emitter,
        locales: Sequence[HHDLocale],
        ctx: Context,
    ):
        with self.cond:
            for handler in [self.handler, self.uhandler]:
                handler.settings = settings
                handler.conf = conf
                handler.info = info
                handler.profiles = profiles
                handler.emit = emit
                handler.locales = locales
                handler.ctx = ctx
            if not hasattr(self.handler, "user_lang"):
                # Only load user lang once to avoid weirdness
                self.handler.user_lang = get_user_lang(ctx)
                self.uhandler.user_lang = self.handler.user_lang
            self.cond.notify_all()

    def open(self):
        self.https = ThreadingSimpleServer(
            ("127.0.0.1" if self.localhost else "", self.port), self.handler
        )
        self.t = Thread(target=self.https.serve_forever)
        self.t.start()

        try:
            if not os.path.exists("/run/hhd"):
                os.mkdir("/run/hhd", 0o700)
            else:
                os.chmod("/run/hhd", 0o700)
            if os.path.exists("/run/hhd/api"):
                os.remove("/run/hhd/api")
            self.unix = UnixHTTPServer("/run/hhd/api", self.uhandler) # type: ignore
            self.tu = Thread(target=self.unix.serve_forever)
            self.tu.start()
        except Exception as e:
            logger.error(f"Error starting server at '/run/hhd/api':\n{e}")

    def close(self):
        if self.https and self.t:
            with self.cond:
                self.cond.notify_all()
            self.https.shutdown()
            self.t.join()
            self.https = None
            self.t = None
        if self.unix and self.tu:
            with self.cond:
                self.cond.notify_all()
            self.unix.shutdown()
            self.tu.join()
            self.unix = None
            self.tu = None
