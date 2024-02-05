import argparse


def evdev():
    from evdev import list_devices, InputDevice
    from time import sleep

    print("Available Devices with the Current Permissions")
    avail = list_devices()
    for i, d in enumerate(avail):
        print(f"{i + 1}:", InputDevice(d))

    print()
    sel = None
    while sel not in avail:
        sel = input("Enter device path (/dev/input/event# or #): ")
        try:
            sel = avail[int(sel) - 1]
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
        print(e)
    print()

    for ev in d.read_loop():
        print(ev)
        sleep(0.001)


def hidraw():
    from hhd.controller.lib.hid import enumerate_unique, Device
    from hhd.controller.lib.common import hexify
    from time import sleep, time

    print("Available Devices with the Current Permissions")
    avail = []
    for i, d in enumerate(enumerate_unique()):
        avail.append(d["path"])
        print(
            f"{i + 1}:",
            f"{str(d['path'])} {hexify(d['vendor_id'])}:{hexify(d['product_id'])}:"
            + f" Usage Page: 0x{hexify(d['usage_page'])} Usage: 0x{hexify(d['usage'])}"
            + f" Names '{d['manufacturer_string']}': '{d['product_string']}'",
        )

    print()
    sel = None
    while sel not in avail:
        sel = input("Enter device path (/dev/input/event# or #): ")
        try:
            sel = avail[int(sel) - 1]
        except Exception:
            sel = sel.encode()

    print()
    d = Device(path=sel)
    print(f"Selected device `{str(sel)}`.")

    start = time()
    for i in range(100000000):
        print(f"{i:6d}: {time() - start:7.4f}", d.read().hex())
        sleep(0.001)


def main():
    parser = argparse.ArgumentParser(
        prog="HHD: Handheld Daemon contribution helper scripts",
        description="Scripts to automate the capture of events, etc.",
    )
    parser.add_argument(
        "command",
        nargs="+",
        default=[],
        help="Supported commands: `evdev`, `hidraw`",
    )
    args = parser.parse_args()

    try:
        match c := args.command[0]:
            case "evdev":
                evdev()
            case "hidraw":
                hidraw()
            case _:
                print(f"Command `{c}` not supported.")
    except KeyboardInterrupt:
        pass

