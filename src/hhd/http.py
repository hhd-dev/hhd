from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RestHandler(BaseHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header("Content-type", "text / html")
        self.end_headers()

    def do_GET(self):
        logging.info(f"GET request\nPath:{self.path}\nHeaders:\n{self.headers}")
        logger.info(self.__dict__)
        self._set_response()
        self.wfile.write("GET request for {}".format(self.path).encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        logging.info(
            f"POST request\nPath:{self.path}\nHeaders:\n{self.headers}{post_data.decode('utf-8')}"
        )

        self._set_response()
        self.wfile.write("POST request for {}".format(self.path).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_http_api(localhost: bool, port: int):
    https = HTTPServer(("127.0.0.1" if localhost else "", port), RestHandler)

    t = Thread(target=https.serve_forever)
    t.start()

    # return https
    return https
