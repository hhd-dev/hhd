import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread, Condition
from typing import Any, Mapping
from urllib.parse import urlparse

from .plugins import Config, Emitter

logger = logging.getLogger(__name__)

STANDARD_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Credentials": "true",
    "WWW-Authenticate": "Bearer",
}

ERROR_HEADERS = {**STANDARD_HEADERS, "Content-type": "text / plain"}
AUTH_HEADERS = ERROR_HEADERS
OK_HEADERS = {**STANDARD_HEADERS, "Content-type": "text / json"}


class RestHandler(BaseHTTPRequestHandler):
    cond: Condition
    conf: Config
    profiles: Mapping[str, Config]
    emit: Emitter
    token: str | None

    def set_response(self, code: int, headers: dict[str, str] = {}):
        self.send_response(code)
        for title, head in headers.items():
            self.send_header(title, head)
        self.end_headers()

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

        self.set_response(401, {"Content-type": "text / plain"})
        self.wfile.write(
            f"Handheld Daemon Error: Authentication is on and you did not supply the proper bearer token.".encode()
        )

        return False

    def set_response_ok(self):
        self.set_response(200, STANDARD_HEADERS)

    def send_error(self, error: str):
        self.set_response(200, ERROR_HEADERS)
        self.wfile.write(error.encode())

    def do_GET(self):
        if not self.send_authenticate():
            return

        self.set_response_ok()

        url = urlparse(self.path)
        logging.info(f"GET request\nPath:{url}\nHeaders:\n{self.headers}")
        json = '{"json": "' + self.path + '"}'
        self.wfile.write(json.encode())

    def do_POST(self):
        if not self.send_authenticate():
            return

        self.set_response_ok()

        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        logging.info(
            f"POST request\nPath:{urlparse(self.path)}\nHeaders:\n{self.headers}{post_data.decode('utf-8')}"
        )

        self.set_response(401, {"Content-type": "text/ json"})
        self.wfile.write("POST request for {}".format(self.path).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_http_api(
    cond: Condition,
    conf: Config,
    profiles: Mapping[str, Config],
    emit: Emitter,
    localhost: bool,
    port: int,
    token: str | None,
):
    # Have to subclass to create closure
    class NewRestHandler(RestHandler):
        pass

    NewRestHandler.cond = cond
    NewRestHandler.conf = conf
    NewRestHandler.profiles = profiles
    NewRestHandler.emit = emit
    NewRestHandler.token = token

    https = HTTPServer(("127.0.0.1" if localhost else "", port), NewRestHandler)

    t = Thread(target=https.serve_forever)
    t.start()

    # return https
    return https
