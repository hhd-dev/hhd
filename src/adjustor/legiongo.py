"""
Legion Go specific code.
"""

import argparse
import subprocess
import logging


# This function is used to execute ACPI commands that are specific to the Legion Go using manufacturer specific ACPI calls.
def execute_acpi_command(command_parts):
    """
    Executes an ACPI command and returns the output.
    """
    command = " ".join(command_parts)
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing command: {e.stderr}")
        return None


def set_tdp_value(mode, wattage):
    mode_mappings = {'Slow': '0x01', 'Steady': '0x02', 'Fast': '0x03'}
    if mode not in mode_mappings:
        logging.error(f"Invalid TDP mode: {mode}. Must be one of {list(mode_mappings.keys())}.")
        return None

    # Adjust these ranges as needed
    if not (3 <= wattage <= 40):  # Assuming wattage should be in a certain range
        logging.error(f"Invalid wattage: {wattage}. Must be between 0 and 100.")
        return None

    mode_code = mode_mappings[mode]
    command_parts = [f"echo '\\_SB.GZFD.WMAE 0 0x12 {{0x00, 0xFF, {mode_code}, 0x01, {wattage}, 0x00, 0x00, 0x00}}' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call"]
    output = execute_acpi_command(command_parts)
    logging.info(f"TDP set to {mode} mode with wattage {wattage}.")
    return output

def get_tdp_value(mode):
    mode_mappings = {'Slow': '01', 'Steady': '02', 'Fast': '03'}
    mode_code = mode_mappings.get(mode, '02')  # Default to 'Steady' if mode is not found
    command_parts = [f"echo '\\_SB.GZFD.WMAE 0 0x11 0x01{mode_code}FF00' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call"]
    response = execute_acpi_command(command_parts)
    if response:
        return response
    else:
        logging.error("Failed to retrieve TDP value.")
        return None


def main():
    parser = argparse.ArgumentParser(description='Legion Go Control Script')
    parser.add_argument('--set-tdp', nargs=2, metavar=('MODE', 'WATTAGE'), help='Set TDP value. Modes: Slow, Steady, Fast.')
    parser.add_argument('--get-tdp', metavar='MODE', help='Get TDP value for a specific mode. Modes: Slow, Steady, Fast.')
    parser.add_argument('--set-fan-curve', nargs='+', type=int, help='Set fan curve. Pass fan speeds as a list.')
    

    args = parser.parse_args()

    if args.set_tdp:
        mode, wattage = args.set_tdp
        set_tdp_value(mode, int(wattage))

    if args.get_tdp:
        get_tdp_value(args.get_tdp)

    if args.set_fan_curve:
        set_fan_curve(args.set_fan_curve)

    

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()