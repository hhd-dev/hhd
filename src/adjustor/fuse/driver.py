# This code is based on the example code from fuse-python
# Technically, the original file is LGPL. My additions are GPL.
#
# Original copyrights:
#    Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>
#    Copyright (C) 2006  Csaba Henk  <csaba.henk@creo.hu>

# Protocol:
# The server sends commands to the client.
# It may not send multiple commands without waiting for a reply.
# The reply is always to the last command.
# All commands are 1024 bytes long.
#
# Commands have the following format:
# "cmd:<command_name>:<arg1>:<arg2>\n"
# "ack:<response>\n"
#
# The following commands are supported:
# "cmd:get:<name>\n"
# "cmd:set:<name>:<val>\n"
#
# The get command will return the current value of the attribute ("ack:<value>\n").
# The set command will set the value of the attribute and just ack ("ack\n").

from __future__ import print_function

import fcntl
import io
import os
import socket
import sys
from errno import *  # type: ignore
from stat import *  # type: ignore
from threading import Lock

import fuse
from fuse import Fuse

FUSE_MOUNT_DIR = "/run/hhd-tdp/"
FUSE_MOUNT_SOCKET = "/run/hhd-tdp/socket"
TIMEOUT = 1
PACK_SIZE = 1024
fuse.fuse_python_api = (0, 2)


class VirtualStat(fuse.Stat):
    def __init__(self):
        self.st_mode = 33206
        self.st_ino = 0
        self.st_dev = 80
        self.st_nlink = 1
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = 4096
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0


VIRTUAL_FILES = [
    "power1_cap_default",
    "power1_cap_min",
    "power1_cap_max",
    "power1_cap",
    "power2_cap_default",
    "power2_cap_min",
    "power2_cap_max",
    "power2_cap",
]


def is_virtual_file(path):
    return path.split("/")[-1] in VIRTUAL_FILES


def flag2mode(flags):
    md = {os.O_RDONLY: "rb", os.O_WRONLY: "wb", os.O_RDWR: "wb+"}
    m = md[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]

    if flags | os.O_APPEND:
        m = m.replace("w", "a", 1)

    return m


class Xmp(Fuse):

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.root = "/"

    def getattr(self, path):
        if "power1_cap" in path or "power2_cap" in path:
            # Stub attributes for power1_cap and power2_cap
            return VirtualStat()
        return os.lstat("." + path)

    def readlink(self, path):
        return os.readlink("." + path)

    def readdir(self, path, offset):
        for e in os.listdir("." + path):
            yield fuse.Direntry(e)

        if path == "/" or (
            path.startswith("/hwmon/hwmon") and len(path.split("/")) <= 4
        ):
            for e in VIRTUAL_FILES:
                yield fuse.Direntry(e)

    def unlink(self, path):
        os.unlink("." + path)

    def rmdir(self, path):
        os.rmdir("." + path)

    def symlink(self, path, path1):
        os.symlink(path, "." + path1)

    def rename(self, path, path1):
        os.rename("." + path, "." + path1)

    def link(self, path, path1):
        os.link("." + path, "." + path1)

    def chmod(self, path, mode):
        os.chmod("." + path, mode)

    def chown(self, path, user, group):
        os.chown("." + path, user, group)

    def truncate(self, path, len):
        if is_virtual_file(path):
            return
        f = open("." + path, "a")
        f.truncate(len)
        f.close()

    def mknod(self, path, mode, dev):
        os.mknod("." + path, mode, dev)

    def mkdir(self, path, mode):
        os.mkdir("." + path, mode)

    def utime(self, path, times):
        os.utime("." + path, times)

    def access(self, path, mode):
        if is_virtual_file(path):
            return 0
        if not os.access("." + path, mode):
            return -EACCES

    def statfs(self):
        return os.statvfs(".")

    def fsinit(self):
        os.chdir(self.root)

    def main(self, *a, passthrough=False, **kw):
        os.makedirs(FUSE_MOUNT_DIR, exist_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(FUSE_MOUNT_SOCKET)
        sock.listen(10)

        self.file_class = XmpFile
        XmpFile.h = Handler(sock)
        XmpFile.cache = {}
        XmpFile.passthrough = passthrough

        code = Fuse.main(self, *a, **kw)
        sock.close()
        return code


class Handler:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.conn = None

    def get_conn(self, retry: bool = False):
        if not retry and self.conn:
            return self.conn
        try:
            self.sock.settimeout(0.05)
            conn, _ = self.sock.accept()
            print("New connection: " + str(conn))
            if self.conn:
                self.conn.close()
            self.conn = conn
        except socket.timeout as e:
            pass
        return self.conn


class XmpFile:
    h: Handler
    cache: dict[str, bytes]
    passthrough: bool

    def __init__(self, path, flags, *mode):
        self.path = path
        power_attr = "power1_cap" in path or "power2_cap" in path
        # Allow passing through writes if we are the steam deck
        passthrough = XmpFile.passthrough and path.endswith("_cap")

        if power_attr and not passthrough:
            print(f"GPU Attribute access: {path} {flags} {mode}")

            # Receive file contents from hhd
            endpoint = path.split("/")[-1]
            cmd = f"cmd:get:{endpoint}\n".encode()
            contents = None
            for i in range(2):
                # For the first read, do not peak at accept
                # If the connection fails, try once more
                # after looking at the accept queue.
                # If it does not work, fail the request.
                # For the rest of the requests, do not check the queue.
                try:
                    conn = self.h.get_conn(bool(i))
                    if not conn:
                        raise RuntimeError(
                            "No active connection. Can not access GPU attributes."
                        )
                    conn.settimeout(TIMEOUT)
                    conn.send(cmd + bytes(PACK_SIZE - len(cmd)))

                    resp = b"/"
                    while resp and not resp.startswith(b"ack:"):
                        conn.settimeout(TIMEOUT)
                        resp = conn.recv(PACK_SIZE)
                    contents = resp[4:]
                    XmpFile.cache[endpoint] = contents
                    break
                except Exception as e:
                    if i:
                        if endpoint in XmpFile.cache:
                            print("No connection available. Using cached value.")
                            contents = XmpFile.cache[endpoint]
                        else:
                            print("Socket failed, could not serve request.")
                            raise

            assert contents
            self.file = io.BytesIO(contents)
            self.fd = -1
            self.virtual = True
        else:
            # print(f"GPU Attribute access: {path} {flags} {mode}")
            self.file = os.fdopen(os.open("." + path, flags, *mode), flag2mode(flags))
            self.fd = self.file.fileno()
            self.virtual = False

        self.wrote = False
        if hasattr(os, "pread") and not self.virtual:
            self.iolock = None
        else:
            self.iolock = Lock()

    def read(self, length, offset):
        if self.iolock:
            self.iolock.acquire()
            try:
                self.file.seek(offset)
                return self.file.read(length)
            finally:
                self.iolock.release()
        else:
            return os.pread(self.fd, length, offset)

    def write(self, buf, offset):
        self.wrote = True
        if self.iolock:
            self.iolock.acquire()
            try:
                self.file.seek(offset)
                self.file.write(buf)
                return len(buf)
            finally:
                self.iolock.release()
        else:
            return os.pwrite(self.fd, buf, offset)

    def release(self, flags):
        try:
            if self.virtual and self.wrote:
                # Send file contents to hhd
                endpoint = self.path.split("/")[-1]
                conn = self.h.get_conn()
                if not conn:
                    raise RuntimeError(
                        "No active connection. Can not access GPU attributes."
                    )

                cmd = f"cmd:set:{endpoint}:".encode()
                self.file.seek(0)
                contents = self.file.read()
                if b"\0" in contents:
                    contents = contents[: contents.index(b"\0")]
                if len(contents) + len(cmd) + 1 > PACK_SIZE:
                    raise ValueError(f"Contents too large to send:\n{contents}")
                stcmd = (
                    cmd
                    + contents
                    + b"\n"
                    + bytes(PACK_SIZE - len(cmd) - len(contents) - 1)
                )
                conn.settimeout(TIMEOUT)
                conn.send(stcmd)
                resp = b""
                while resp and not resp.startswith(b"ack\n"):
                    conn.settimeout(TIMEOUT)
                    resp = conn.recv(1024).strip()
        except Exception as e:
            print(f"Error sending file contents to hhd. Closing properly. Error:\n{e}")
        finally:
            self.file.close()

    def _fflush(self):
        if "w" in self.file.mode or "a" in self.file.mode:
            self.file.flush()

    def fsync(self, isfsyncfile):
        if self.virtual:
            return
        self._fflush()
        if isfsyncfile and hasattr(os, "fdatasync"):
            os.fdatasync(self.fd)
        else:
            os.fsync(self.fd)

    def flush(self):
        if self.virtual:
            return
        self._fflush()
        # cf. xmp_flush() in fusexmp_fh.c
        os.close(os.dup(self.fd))

    def fgetattr(self):
        if self.virtual:
            return VirtualStat()
        return os.fstat(self.fd)

    def ftruncate(self, len):
        self.file.truncate(len)

    def lock(self, cmd, owner, **kw):
        if self.virtual:
            return -EINVAL
        op = {
            fcntl.F_UNLCK: fcntl.LOCK_UN,
            fcntl.F_RDLCK: fcntl.LOCK_SH,
            fcntl.F_WRLCK: fcntl.LOCK_EX,
        }[kw["l_type"]]
        if cmd == fcntl.F_GETLK:
            return -EOPNOTSUPP
        elif cmd == fcntl.F_SETLK:
            if op != fcntl.LOCK_UN:
                op |= fcntl.LOCK_NB
        elif cmd == fcntl.F_SETLKW:
            pass
        else:
            return -EINVAL

        fcntl.lockf(self.fd, op, kw["l_start"], kw["l_len"])


def main():
    sock = None
    try:
        server = Xmp(
            version="%prog " + fuse.__version__, usage="", dash_s_do="setsingle"
        )
        server.parser.add_option(
            mountopt="root",
            metavar="PATH",
            default="/",
            help="GPU device private bind mount point",
        )
        server.parser.add_option(
            mountopt="passthrough",
            metavar="PASSTHROUGH",
            action="store_true",
            default=False,
            help="Allow tdp write passthrough, e.g., for the Steam Deck.",
        )
        server.parse(values=server, errex=1)

        try:
            if server.fuse_args.mount_expected():
                os.chdir(server.root)
        except OSError:
            print("can't enter root of underlying filesystem", file=sys.stderr)
            sys.exit(1)

        server.main(passthrough=getattr(server, "passthrough", False))
    except KeyboardInterrupt:
        pass
    finally:
        if sock:
            sock.close()


if __name__ == "__main__":
    main()
