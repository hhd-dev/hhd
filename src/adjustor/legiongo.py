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
        logging.debug(f"Command: {command}")
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

def set_fan_curve(fan_table):
    """
    Sets a new fan curve based on the provided fan table array.
    The fan table should contain fan speed values that correspond to different temperature thresholds.

    Args:
        fan_table (list): An array of fan speeds to set the fan curve.

    Returns:
        str: The output from setting the new fan curve.
    """
    # Assuming Fan ID and Sensor ID are both 0 (as they are ignored)
    fan_id_sensor_id = '0x00, 0x00'

    # Assuming the temperature array length and values are ignored but required
    temp_array_length = '0x0A, 0x00, 0x00, 0x00'  # Length 10 in hex
    temp_values = ', '.join([f'0x{temp:02x}, 0x00' for temp in range(0, 101, 10)]) + ', 0x00'

    # Fan speed values in uint16 format with null termination
    fan_speed_values = ', '.join([f'0x{speed:02x}, 0x00' for speed in fan_table]) + ', 0x00'

    # Constructing the full command
    logging.info(f"Setting fan curve to: {fan_table}")
    
    command = ["echo '\\_SB.GZFD.WMAB 0 0x06 {{{fan_id_sensor_id}, {temp_array_length}, {fan_speed_values}, {temp_array_length}, {temp_values}}}' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call".format(
        fan_id_sensor_id=fan_id_sensor_id,
        temp_array_length=temp_array_length,
        temp_values=temp_values,
        fan_speed_values=fan_speed_values
    )]
    return execute_acpi_command(command)


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

def set_full_speed(state):
    """
    Sets the fan speed to 100% bypassing the fan curve.
    """
    if state == 1:
        logging.info("Setting fan speed to 100%")
        command = ["echo '\\_SB.GZFD.WMAE 0 0x12 0x0104020100' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call"]
    else:
        logging.info("Setting fan speed to fan curve value.")
        command = ["echo '\\_SB.GZFD.WMAE 0 0x12 0x0004020000' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call"]
    return execute_acpi_command(command)

def set_smart_fan_mode(mode_value):
    """
    Set the Smart Fan Mode of the system. This controls the system's cooling behavior, balancing
    between cooling performance and noise level.

    Args:
        mode_value (int): The value of the Smart Fan Mode to set. Known values are:
                          - 1: Quiet Mode (Blue LED)
                          - 2: Balanced Mode    (White LED)
                          - 3: Performance Mode (Red LED)
                          - 224: Extreme Mode (Green LED?) Possible extreme power saving mode?
                          - 255: Custom Mode (Purple LED)

    Returns:
        str: The result of the operation, or an error message if the operation fails.
    """
    valid_modes = [1, 2,3, 224, 255]
    if mode_value not in valid_modes:
        logging.error(f"Invalid mode_value. Must be one of {valid_modes}.")
        return "Invalid mode_value provided."
    # Construct and execute the ACPI command
    command = ["echo '\\_SB.GZFD.WMAA 0 0x2C {mode_value}' | sudo tee /proc/acpi/call; sudo cat /proc/acpi/call".format(mode_value=mode_value)]
    return execute_acpi_command(command)

def main():
    parser = argparse.ArgumentParser(description='Legion Go Control Script')
    parser.add_argument('--set-smart-fan-mode', nargs=1, type=int, metavar='value', help='Set the Smart Fan Mode. Known values are: 1: Quiet Mode (Blue LED), 2: Balanced Mode (White LED), 3: Performance Mode (Red LED), 224: Extreme Mode, 255: Custom Mode (Purple LED).')
    parser.add_argument('--set-tdp', nargs=2, metavar=('MODE', 'WATTAGE'), help='Set TDP value. Modes: Slow, Steady, Fast.')
    parser.add_argument('--get-tdp', metavar='MODE', help='Get TDP value for a specific mode. Modes: Slow, Steady, Fast. Use ALL to get all modes.')
    parser.add_argument('--set-fan-curve', nargs=10, type=int, metavar='int',  help='Set fan curve. Provide a series of fan speeds. i.e --set-fan-curve 0 10 20 30 40 50 60 70 80 90 100. Sets the fan speed to 0%% at 0°C, 10%% at 10°C, 20%% at 20°C, etc.')
    parser.add_argument('--set-full-speed', nargs=1, type=int, metavar='value', help='Set fan speed to 100%% bypassing the fan curve, accepts 1 or 0.')
    parser.add_argument('--get-fan-curve', action='store_true', help='Get fan curve, retuns a list of fan speeds for different temperature thresholds.') 
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging, prints executed commands and their output.')
    args = parser.parse_args()


    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.set_smart_fan_mode:
        set_smart_fan_mode(args.set_smart_fan_mode[0])

    if args.set_tdp:
        mode, wattage = args.set_tdp
        print(args.set_tdp)
        set_tdp_value(mode, int(wattage))

    if args.get_tdp:
        if args.get_tdp == 'ALL':
            for mode in ['Slow', 'Steady', 'Fast']:
                get_tdp_value(mode)
        else:
            get_tdp_value(args.get_tdp)

    if args.set_fan_curve:
        set_fan_curve(args.set_fan_curve)

    if args.set_full_speed:
        set_full_speed(args.set_full_speed[0])

    if args.get_fan_curve:
        get_fan_curve()

    if not any(vars(args).values()):
        parser.print_help()
    

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()