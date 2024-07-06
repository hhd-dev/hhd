#!/usr/bin/env python3

import fcntl
import os
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BASE_NAME = "org.freedesktop.UPower.PowerProfiles"
BASE_PATH = "/org/freedesktop/UPower/PowerProfiles"
LEGACY_NAME = "net.hadess.PowerProfiles"
LEGACY_PATH = "/net/hadess/PowerProfiles"
XML_PATH = "power-profiles-daemon.dbus.xml.in"

SUPPORTED_PROFILES = {
    "power-saver": "power",
    "balanced": "balanced",
    "performance": "performance",
}
SUPPORTED_PROFILES_REVERSE = {v: k for k, v in SUPPORTED_PROFILES.items()}


def load_introspect(legacy=False):
    """Returns the yaml data of a file in the relative dir provided."""
    import inspect
    import os

    script_fn = inspect.currentframe().f_back.f_globals["__file__"]  # type: ignore
    dirname = os.path.dirname(script_fn)
    with open(os.path.join(dirname, XML_PATH), "r") as f:
        base = f.read()
        return base.replace(
            "@dbus_iface@", LEGACY_NAME if legacy else BASE_NAME
        ).replace("@dbus_path@", LEGACY_PATH if legacy else BASE_PATH)


def iface(legacy: bool):
    return LEGACY_NAME if legacy else BASE_NAME


def gpath(legacy: bool):
    return LEGACY_PATH if legacy else BASE_PATH


def create_interface(legacy: bool):
    class HhdPpd(dbus.service.Object):

        def __init__(self, conn=None):
            self.profile_holds = []
            self.actions = []
            self.profile = "power-saver"  # next(iter(SUPPORTED_PROFILES))

            super().__init__(conn, gpath(legacy), None)

        @dbus.service.method(
            dbus.INTROSPECTABLE_IFACE, in_signature="", out_signature="s"
        )
        def Introspect(self):
            return load_introspect(legacy)

        @dbus.service.method(
            dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v"
        )
        def Get(self, interface_name, property_name):
            return self.GetAll(interface_name)[property_name]

        @dbus.service.method(
            dbus.PROPERTIES_IFACE,
            in_signature="s",
            out_signature="a{sv}",
            sender_keyword="sender",
        )
        def GetAll(self, interface_name, sender=None):
            if interface_name == iface(legacy):
                return {
                    "Actions": ["trickle_charge"],
                    "ActiveProfile": self.profile,
                    "ActiveProfileHolds": dbus.Array(self.profile_holds, signature="u"),
                    "PerformanceDegraded": "",
                    "PerformanceInhibited": "",
                    "Profiles": [
                        {
                            "Profile": dbus.String(p, variant_level=1),
                            "CpuDriver": dbus.String("amd_pstate", variant_level=1),
                            "PlatformDriver": dbus.String(
                                "platform_profile", variant_level=1
                            ),
                            "Driver": dbus.String("multiple", variant_level=1),
                        }
                        for p in SUPPORTED_PROFILES
                    ],
                    "Version": "0.21",
                }
            else:
                raise dbus.exceptions.DBusException(
                    "com.example.UnknownInterface",
                    "Handheld daemon does not implement the %s interface."
                    % interface_name,
                )

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv")
        def Set(self, interface_name, property_name, new_value):
            # validate the property name and value, update internal state…
            self.PropertiesChanged(interface_name, {property_name: new_value}, [])

        @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
        def PropertiesChanged(
            self, interface_name, changed_properties, invalidated_properties
        ):
            if interface_name != iface(legacy):
                return

            for k, v in changed_properties.items():
                if not k == "ActiveProfile":
                    continue
                if v not in SUPPORTED_PROFILES:
                    continue
                np = SUPPORTED_PROFILES[v]
                if np == self.profile:
                    continue
                print(np, flush=True)

        @dbus.service.method(iface(legacy), in_signature="sss", out_signature="u")
        def HoldProfile(self, profile: str, reason: str, application_id: str):
            # TODO
            return 1

        @dbus.service.method(iface(legacy), in_signature="u", out_signature="")
        def ReleaseProfile(self, handle: int):
            # TODO
            self.ProfileReleased(handle)

        @dbus.service.signal(iface(legacy), signature="u")
        def ProfileReleased(self, handle: int):
            # TODO
            return handle

        def update_profile(self):
            for line in sys.stdin:
                if not line:
                    break
                profile = line.strip()
                if profile not in SUPPORTED_PROFILES_REVERSE:
                    continue

                self.profile = profile
                self.PropertiesChanged(
                    iface(legacy), {"ActiveProfile": self.profile}, []
                )
            return True

    return HhdPpd


if __name__ == "__main__":
    mainloop = None
    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        # set sys.stdin non-blocking
        orig_fl = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

        legacy = True
        session_bus = dbus.SystemBus()
        name = dbus.service.BusName(iface(legacy), session_bus)
        object = create_interface(legacy)(session_bus)

        GLib.timeout_add(100, object.update_profile)
        mainloop = GLib.MainLoop()
        mainloop.run()
    except KeyboardInterrupt:
        if mainloop:
            mainloop.quit()
