def evdev():
    from evdev import list_devices, InputDevice, categorize
    from time import sleep, perf_counter

    print("Available Devices with the Current Permissions")
    avail = list_devices()
    for d in avail:
        print(InputDevice(d))

    print()
    sel = None
    while sel not in avail:
        sel = input("Enter device path (/dev/input/event# or #): ")
        try:
            sel = f"/dev/input/event{int(sel)}"
        except Exception as e:
            pass

    print()
    d = InputDevice(sel)
    print(f"Selected device `{d}`.")
    print("Capabilities")
    print(d.capabilities(verbose=True))

    try:
        print("Attempting to grab device.")
        d.grab()
    except Exception as e:
        print("Could not grab device, error:")
        print("\nYou may continue.")
    print()

    endcap = False
    start = perf_counter()
    for ev in d.read_loop():
        curr = perf_counter() - start
        if ev.code == 0 and ev.type == 0 and ev.value == 0:
            print(
                f"└ SYN ─ {curr:7.3}s ────────────────────────────────────────────────────────┘"
            )
            endcap = True
        else:
            if endcap:
                print(
                    "\n┌────────────────────────────────────────────────────────────────────────┐"
                )
                endcap = False
            print(f"│ {str(categorize(ev)):>70s} │")
        sleep(0.001)


def hidraw():
    from hhd.controller.lib.hid import enumerate_unique, Device
    from hhd.controller.lib.common import hexify
    from time import sleep, time

    print("Available Devices with the Current Permissions")
    avail = []
    infos = {}
    for i, d in enumerate(enumerate_unique()):
        avail.append(d["path"])
        n = int(d["path"].decode().split("hidraw")[1])
        infos[n] = (
            f"{d['path'].decode():15s} {hexify(d['vendor_id'])}:{hexify(d['product_id'])}:"
            + f" Usage Page: 0x{hexify(d['usage_page'])} Usage: 0x{hexify(d['usage'])}"
            + f" Names '{d['manufacturer_string']}': '{d['product_string']}'"
        )
    print("\n".join([infos[k] for k in sorted(infos)]))

    print()
    sel = None
    while sel not in avail:
        sel = input("Enter device path (/dev/hidraw# or #): ")
        try:
            sel = f"/dev/hidraw{int(sel)}".encode()
        except Exception:
            sel = sel.encode()

    print()
    d = Device(path=sel)
    print(f"Selected device `{str(sel)}`.")

    start = time()
    for i in range(100000000):
        print(f"{i:6d}: {time() - start:8.4f}", d.read().hex())
        sleep(0.001)
