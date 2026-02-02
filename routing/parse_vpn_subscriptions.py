#!/usr/bin/env python3
"""
Parse VPN subscription data from text or XML file and convert to JSON.

Supports two input formats:
1. Text format: Fixed-width columns with VPN sections
2. XML format: SEMP XML output with subscription elements
"""

import re
import json
import sys
import xml.etree.ElementTree as ET


def expand_flag_type(flag):
    """Expand destination type flag to full name."""
    mapping = {
        'C': 'client',
        'Q': 'queue',
        'R': 'remote-router'
    }
    return mapping.get(flag, flag)


def expand_flag_persistence(flag):
    """Expand persistence flag to full name."""
    mapping = {
        'P': 'persistent',
        'N': 'non-persistent'
    }
    return mapping.get(flag, flag)


def expand_flag_redundancy(flag):
    """Expand redundancy flag to full name."""
    mapping = {
        'P': 'primary',
        'B': 'backup',
        'S': 'static',
        '-': 'not-applicable'
    }
    return mapping.get(flag, flag)


def detect_file_format(filename):
    """
    Detect whether the file is XML or text format.

    Returns:
        'xml' if XML format, 'text' if text format, None if unknown
    """
    try:
        with open(filename, 'r') as f:
            first_line = f.readline().strip()

            # Check if it starts with XML tag
            if first_line.startswith('<?xml') or first_line.startswith('<rpc-reply'):
                return 'xml'

            # Check if it looks like the text format (Flags Legend or Message VPN)
            if 'Flags Legend:' in first_line or first_line == '':
                # Read a bit more to confirm
                for line in f:
                    if 'Flags Legend:' in line or 'Message VPN' in line:
                        return 'text'
                    if line.strip():  # Non-empty line that doesn't match
                        break

            return None
    except Exception as e:
        print(f"Error detecting file format: {e}", file=sys.stderr)
        return None


def parse_xml_file(filename):
    """Parse XML format VPN subscription file."""
    try:
        tree = ET.parse(filename)
        root = tree.getroot()

        # Navigate to subscriptions: rpc > show > smrp > subscriptions > subscription
        subscriptions = []

        # Find all subscription elements
        # The path might vary, so let's search for all 'subscription' elements
        for sub_elem in root.findall('.//subscription'):
            vpn_name = sub_elem.findtext('vpn-name', '').strip()
            destination_name = sub_elem.findtext('destination-name', '').strip()
            destination_type = sub_elem.findtext('destination-type', '').strip()
            persistence = sub_elem.findtext('persistence', '').strip()
            redundancy = sub_elem.findtext('redundancy', '').strip()
            block_id = sub_elem.findtext('block-id', '').strip()
            dto_priority = sub_elem.findtext('dto-priority', '').strip()
            # In XML it's called 'topic' instead of 'subscription'
            topic = sub_elem.findtext('topic', '').strip()

            subscription = {
                'vpn_name': vpn_name,
                'destination_name': destination_name,
                'destination_type': destination_type,
                'persistence': persistence,
                'redundancy': redundancy,
                'block_id': block_id,
                'dto_priority': dto_priority,
                'subscription': topic
            }
            subscriptions.append(subscription)

        if not subscriptions:
            raise ValueError("No subscription elements found in XML file")

        return {'subscriptions': subscriptions}

    except ET.ParseError as e:
        raise ValueError(f"Invalid XML format: {e}")
    except Exception as e:
        raise ValueError(f"Error parsing XML file: {e}")


def parse_text_file(filename):
    """Parse the VPN subscription file and return structured data."""

    with open(filename, 'r') as f:
        lines = f.readlines()

    vpns = []
    current_vpn = None
    current_entry = None
    in_data_section = False

    for line_num, line in enumerate(lines, 1):
        # Remove newline but preserve spaces for indentation detection
        line = line.rstrip('\n')

        # Skip empty lines
        if not line.strip():
            continue

        # Skip legend lines
        if line.startswith('Flags Legend:') or line.startswith('T -') or \
           line.startswith('P -') or line.startswith('R -') or \
           line.strip().startswith('R=remote-router') or \
           line.strip().startswith('S=static'):
            continue

        # Check for VPN header: "Message VPN : prod (exported: No; 100% complete)"
        vpn_match = re.match(r'Message VPN\s*:\s*(\S+)\s*\(exported:\s*(\w+);\s*(.+)\)', line)
        if vpn_match:
            # Save previous VPN if exists
            if current_vpn is not None:
                if current_entry is not None:
                    current_vpn['subscriptions'].append(current_entry)
                vpns.append(current_vpn)

            # Start new VPN section
            vpn_name = vpn_match.group(1)
            exported = vpn_match.group(2)
            completion = vpn_match.group(3)

            current_vpn = {
                'vpn_name': vpn_name,
                'exported': exported,
                'completion': completion,
                'subscriptions': []
            }
            current_entry = None
            in_data_section = False
            continue

        # Skip header and separator lines
        if 'Destination Name' in line and 'Flags' in line:
            in_data_section = True
            continue
        if line.strip().startswith('T P R') or line.strip().startswith('---'):
            continue

        # Process data lines (only after we've seen headers)
        if in_data_section and current_vpn is not None:
            # Check if this is a continuation line (starts with 2+ spaces)
            if line.startswith('  '):
                # This is a continuation line
                if current_entry is not None:
                    # Parse continuation line using fixed-width columns
                    # The destination name continues up to column 25
                    # The subscription continues from column 41
                    dest_part = line[:25].strip()
                    sub_part = line[41:].strip() if len(line) > 41 else ''

                    if dest_part:
                        current_entry['destination_name'] += dest_part
                    if sub_part:
                        if current_entry['subscription']:
                            current_entry['subscription'] += sub_part
                        else:
                            current_entry['subscription'] = sub_part
            else:
                # This is a new entry line
                # Save previous entry
                if current_entry is not None:
                    current_vpn['subscriptions'].append(current_entry)

                # Parse the new entry using fixed-width columns
                # Format based on header alignment:
                # Destination Name: columns 0-24
                # Flag T: column 25
                # Flag P: column 27
                # Flag R: column 29
                # BlkID: columns 30-35 (right-aligned)
                # DTO Prio: columns 36-40 (right-aligned)
                # Subscription: column 41+

                destination_name = line[:25].strip()
                flag_t = line[25:26].strip() if len(line) > 25 else ''
                flag_p = line[27:28].strip() if len(line) > 27 else ''
                flag_r = line[29:30].strip() if len(line) > 29 else ''
                blk_id = line[30:36].strip() if len(line) > 30 else ''
                dto_prio = line[36:41].strip() if len(line) > 36 else ''
                subscription = line[41:].strip() if len(line) > 41 else ''

                # Only create entry if we have minimum required fields
                if destination_name and flag_t:
                    current_entry = {
                        'destination_name': destination_name,
                        'destination_type': expand_flag_type(flag_t),
                        'persistence': expand_flag_persistence(flag_p),
                        'redundancy': expand_flag_redundancy(flag_r),
                        'block_id': blk_id,
                        'dto_priority': dto_prio,
                        'subscription': subscription
                    }
                else:
                    # Malformed line, skip
                    continue

    # Don't forget the last VPN and entry
    if current_entry is not None and current_vpn is not None:
        current_vpn['subscriptions'].append(current_entry)
    if current_vpn is not None:
        vpns.append(current_vpn)

    # Flatten structure: include vpn_name in each subscription
    all_subscriptions = []
    for vpn in vpns:
        vpn_name = vpn['vpn_name']
        for subscription in vpn['subscriptions']:
            # Create new ordered dict with vpn_name first
            ordered_subscription = {
                'vpn_name': vpn_name,
                'destination_name': subscription['destination_name'],
                'destination_type': subscription['destination_type'],
                'persistence': subscription['persistence'],
                'redundancy': subscription['redundancy'],
                'block_id': subscription['block_id'],
                'dto_priority': subscription['dto_priority'],
                'subscription': subscription['subscription']
            }
            all_subscriptions.append(ordered_subscription)

    return {'subscriptions': all_subscriptions}


def print_help():
    """Print help information."""
    help_text = """
VPN Subscription Parser

DESCRIPTION:
    Parses VPN subscription data from text or XML files and converts to JSON format.

    Supported formats:
    1. Text format: Fixed-width columns with VPN sections
    2. XML format: SEMP XML output with subscription elements

    The script automatically detects the input format.

USAGE:
    parse_vpn_subscriptions.py <input_file>
    parse_vpn_subscriptions.py -h | --help

OPTIONS:
    -h, --help      Show this help message and exit

ARGUMENTS:
    input_file      Path to the VPN subscription text file to parse

OUTPUT:
    The script outputs JSON to stdout. You can redirect the output to a file:
        parse_vpn_subscriptions.py input.txt > output.json

EXAMPLES:
    # Parse file and display JSON to terminal
    parse_vpn_subscriptions.py shared_subs_with_noexport.txt

    # Parse file and save to JSON file
    parse_vpn_subscriptions.py shared_subs_with_noexport.txt > vpn_data.json

    # Parse file and pipe to jq for pretty printing
    parse_vpn_subscriptions.py shared_subs_with_noexport.txt | jq .

JSON OUTPUT FORMAT:
    {
      "subscriptions": [
        {
          "vpn_name": "prod",
          "destination_name": "...",
          "destination_type": "client|queue|remote-router",
          "persistence": "persistent|non-persistent",
          "redundancy": "primary|backup|static|not-applicable",
          "block_id": "...",
          "dto_priority": "...",
          "subscription": "..."
        }
      ]
    }
"""
    print(help_text)


def main():
    """Main entry point."""
    # Check for help flag
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help']:
        print_help()
        sys.exit(0 if len(sys.argv) > 1 else 1)

    input_file = sys.argv[1]

    # Detect file format
    file_format = detect_file_format(input_file)

    if file_format is None:
        print("ERROR: Unable to detect file format", file=sys.stderr)
        print("", file=sys.stderr)
        print("Expected formats:", file=sys.stderr)
        print("  1. Text format: Fixed-width columns starting with 'Flags Legend:' or 'Message VPN :'", file=sys.stderr)
        print("  2. XML format: SEMP XML output starting with '<rpc-reply>' or '<?xml'", file=sys.stderr)
        print("", file=sys.stderr)
        print("Please check that your input file is in one of the supported formats.", file=sys.stderr)
        sys.exit(1)

    print(f"Detected format: {file_format}", file=sys.stderr)

    # Parse the file based on detected format
    try:
        if file_format == 'xml':
            data = parse_xml_file(input_file)
        else:  # text
            data = parse_text_file(input_file)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error while parsing file: {e}", file=sys.stderr)
        sys.exit(1)

    # Count subscriptions by VPN (print to stderr so it doesn't interfere with JSON output)
    vpn_counts = {}
    for sub in data['subscriptions']:
        vpn_name = sub['vpn_name']
        vpn_counts[vpn_name] = vpn_counts.get(vpn_name, 0) + 1

    print(f"Successfully parsed {len(data['subscriptions'])} subscription(s)", file=sys.stderr)
    for vpn_name, count in vpn_counts.items():
        print(f"  VPN '{vpn_name}': {count} subscription(s)", file=sys.stderr)

    # Output JSON to stdout
    json.dump(data, sys.stdout, indent=2)
    print()  # Add final newline


if __name__ == '__main__':
    main()
