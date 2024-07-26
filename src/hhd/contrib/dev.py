def evdev(dev: str | None):
    from typing import cast
    from evdev import list_devices, InputDevice, categorize, ecodes
    from time import sleep, perf_counter

    def B(b: str):
        return cast(int, getattr(ecodes, b))

    def RV(type: int, code: int):
        v = ecodes.bytype[type][code]
        if isinstance(v, list):
            return v[0]
        return v

    print("Available Devices with the Current Permissions")
    avail = list_devices()
    for d in avail:
        print(f" - {str(InputDevice(d))}")
    print()

    if dev and dev != "nograb":
        print(f"Using argument '{dev}'.")
        try:
            sel = f"/dev/input/event{int(dev)}"
        except Exception:
            sel = dev
        if sel not in avail:
            print(f"Device '{sel}' not found.")
            return
    else:
        sel =    None
        while sel not in avail:
            try:
                sel = input("Enter device path (/dev/input/event# or #): ")
            except EOFError:
                return
            try:
                sel = f"/dev/input/event{int(sel)}"
            except Exception as e:
                pass
        print()

    d = InputDevice(sel)
    print(f"Selected device `{d}`.")
    print()
    print("Capabilities")
    for (cap_str, cap), vals in d.capabilities(verbose=True).items():
        print(f" - {cap_str} ({cap})")
        for (names, code) in vals:
            if not isinstance(code, int):
                abs_info = code
                names, code = names
            else:
                abs_info = ""
            print(f"   {code:04d}: {', '.join(names) if isinstance(names, list) else names}")
            if abs_info:
                print(f"     > [{str(abs_info)}]")
    try:
        print()
        if dev != "nograb":
            print("Attempting to grab device.")
            d.grab()
            print("Device grabbed, system will not see its events.")
    except Exception as e:
        print(f"Could not grab device, system will still see events. Error:\n{e}")
        print("\nReading events still work.")
    print()
    print(f"Reading from: `{d}`.")

    endcap = True
    start = perf_counter()
    ofs = None
    prev = 0
    for ev in d.read_loop():
        if ofs == None:
            ofs = ev.timestamp()
        curr = perf_counter() - start
        hz = f"{1/(curr - prev):6.1f} Hz" if curr != prev else "   NaN Hz"
        if ev.code == 0 and ev.type == 0 and ev.value == 0:
            print(
                f"└ SYN ─ {curr:7.3f}s ─ {hz} ─────────────────────────────────────┘"
            )
            prev = curr
            endcap = True
        else:
            if endcap:
                print(
                    "\n┌─────────────────────────────────────────────────────────────────┐"
                )
                endcap = False

            evstr = (
                f"{ev.timestamp() - ofs:7.3f}s /"
                + f" {getattr(ecodes, "EV")[ev.type]:>6s} ({ev.type:03d}) /"
                + f" {RV(ev.type, ev.code):>21s} ({ev.code:03d}):"
            )

            if ev.type == B("EV_KEY"):
                match ev.value:
                    case 0:
                        act = "released"
                    case 1:
                        act = " pressed"
                    case 2:
                        act = "repeated"
                    case val:
                        act = f"{val:8d}"
                evstr += f" {act}"
            elif ev.type == B("EV_ABS"):
                evstr += f" {ev.value:8d}"
            else:
                hexval = f"0x{ev.value:04X}"
                evstr += f" {hexval:>8s}"

            print(f"│ {evstr:>58s} │")
        sleep(0.001)


def hidraw(dev: str | None):
    from hhd.controller.lib.hid import enumerate_unique, Device
    from hhd.controller.lib.common import hexify
    from time import sleep, time, perf_counter

    print("Available Devices with the Current Permissions")
    avail = []
    infos = {}
    for i, d in enumerate(enumerate_unique()):
        avail.append(d["path"])
        n = int(d["path"].decode().split("hidraw")[1])
        infos[n] = (
            f" - {d['path'].decode():13s} {hexify(d['vendor_id'])}:{hexify(d['product_id'])}"
            + f" Usage Page: 0x{hexify(d['usage_page'])} Usage: 0x{hexify(d['usage'])}"
            + f" Names: '{d['manufacturer_string']}': '{d['product_string']}'"
        )
    print("\n".join([infos[k] for k in sorted(infos)]))

    print()
    if dev:
        print(f"Using argument '{dev}'.")
        try:
            sel = f"/dev/hidraw{int(dev)}".encode()
        except Exception:
            sel = dev.encode()
        if sel not in avail:
            print(f"Device '{sel.decode()}' not found.")
            return
    else:
        sel = None
        while sel not in avail:
            try:
                sel = input("Enter device path (/dev/hidraw# or #): ")
            except EOFError:
                return
            try:
                sel = f"/dev/hidraw{int(sel)}".encode()
            except Exception:
                sel = sel.encode()
        print()

    d = Device(path=sel)
    print(f"Selected device `{str(sel)}`.")

    start = perf_counter()
    prev = 0
    for i in range(100000000):
        curr = perf_counter() - start
        hz = f"{1/(curr - prev):6.1f} Hz" if curr != prev else "   NaN Hz"
        prev = curr
        print(f"{i:6d}: {curr:8.4f}s ({hz})", d.read().hex())
        sleep(0.0005)
