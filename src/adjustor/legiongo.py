"""
Legion Go specific code.
"""

import argparse
import subprocess
import logging
import re

# This function is used to execute ACPI commands that are specific to the Legion Go using manufacturer specific ACPI calls.
def execute_acpi_command(command_parts):
    """
    Executes an ACPI command and returns the output.
    """
    command = " ".join(command_parts)
    try:
        logging.info(f"Executing command: {command}")
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
        match = re.search(r'\n0x([0-9a-fA-F]+)', response)
        if match:
            tdp_hex = match.group(1)
            tdp_value = int(tdp_hex, 16) # Convert hex to decimal
            logging.info(f"Retrieved TDP value for {mode} mode: {tdp_value}")
        else:
            logging.error("Failed to parse TDP value.")
    else:
        logging.error("Failed to retrieve TDP value.")
    return response

def get_fan_curve():
    # Define the ACPI command to retrieve the fan curve data
    acpi_command_parts = ["echo '\\_SB.GZFD.WMAB 0 0x05 0x0000' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call"]
    response = execute_acpi_command(acpi_command_parts)

    if response:
        try:
            hex_data = response[response.find('{')+1:response.find('}')]
            hex_values = hex_data.split(', ')

            # Convert hex values to integers, handling trailing commas
            fan_speed_values = [int(val.split(',')[0].strip(), 16) for val in hex_values if val.strip()]

            # Skip the first value (indicating starting temperature step) and padding values
            fan_speed_values = fan_speed_values[4:]  # Start from the first actual fan speed value

            formatted_output = "Fan Curve:\n"

            # Process the data assuming the pattern: 0x00, 0x00, 0x00, fan speed
            for i in range(0, len(fan_speed_values), 4):
                temperature = 10 + (i // 4) * 10  # Increment temperature by 10°C starting from 10°C
                speed = fan_speed_values[i]  # Fan speed is the first value in each group of four
                formatted_output += f"Temperature {temperature}°C: Fan Speed {speed}%\n"



            logging.info("Fan Curve Data Retrieved:")
            print(formatted_output)

        except Exception as e:
            logging.error(f"Error parsing fan curve: {e}")
    
    else:
        logging.error("Failed to retrieve fan curve data.")


def main():
    parser = argparse.ArgumentParser(description='Legion Go Control Script')
    parser.add_argument('--set-tdp', nargs=2, metavar=('MODE', 'WATTAGE'), help='Set TDP value. Modes: Slow, Steady, Fast.')
    parser.add_argument('--get-tdp', metavar='MODE', help='Get TDP value for a specific mode. Modes: Slow, Steady, Fast.')
    parser.add_argument('--set-fan-curve', nargs='+', type=int, help='Set fan curve. Pass fan speeds as a list.')
    parser.add_argument('--get-fan-curve', action='store_true', help='Get fan curve.') 
    

    args = parser.parse_args()

    if args.set_tdp:
        mode, wattage = args.set_tdp
        set_tdp_value(mode, int(wattage))

    if args.get_tdp:
        get_tdp_value(args.get_tdp)

    if args.set_fan_curve:
        set_fan_curve(args.set_fan_curve)

    if args.get_fan_curve:
        get_fan_curve()
    

    

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()