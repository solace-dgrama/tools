#!/usr/bin/env python3
"""
Parse and display action lists from reg_vmrRedundancyRandomActions.tcl test logs.

Usage:
    ./parse_action_list.py [OPTIONS] [log_file]

Options:
    --executed         Show executed actions from test output instead of declared action lists
    --list N           Show only list N (use with --executed)
    --help, -h         Show this help message

Arguments:
    log_file           Path to AFW log file (default: /tmp/debug/log.txt)

Examples:
    # Show all declared action lists from default log
    ./parse_action_list.py

    # Show declared action lists from specific log file
    ./parse_action_list.py /tmp/processed/log.txt

    # Show timeline of executed actions
    ./parse_action_list.py /tmp/processed/log.txt --executed

    # Show only executed actions from List 2
    ./parse_action_list.py /tmp/processed/log.txt --executed --list 2

    # Show help
    ./parse_action_list.py --help
"""

import re
import sys
import subprocess
from typing import List, Tuple, Dict
from datetime import datetime


def print_help():
    """Print help message."""
    print(__doc__)
    sys.exit(0)


def extract_action_lists(log_file: str) -> List[Tuple[str, str, str]]:
    """
    Extract action lists from log file using grep.

    Returns list of tuples: (timestamp, full_timestamp_line, action_list_text)
    """
    try:
        # Use grep to find "Action list" entries with 2 lines of context after
        result = subprocess.run(
            ['grep', 'Action list', log_file, '-A', '2'],
            capture_output=True,
            text=True,
            check=True
        )

        lines = result.stdout.strip().split('\n')
        action_lists = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Look for timestamp line with "Action list:"
            if 'Action list:' in line:
                # Extract timestamp [HH:MM:SS]
                timestamp_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = timestamp_match.group(1) if timestamp_match else "Unknown"

                # Skip the "------------" separator line
                i += 1
                if i < len(lines) and '------------' in lines[i]:
                    i += 1

                # Get the action list content (may span multiple lines until next separator)
                action_text = ""
                while i < len(lines) and lines[i] != '--':
                    if lines[i].strip():
                        action_text += lines[i].strip() + " "
                    i += 1

                if action_text.strip():
                    action_lists.append((timestamp, line, action_text.strip()))

            i += 1

        return action_lists

    except subprocess.CalledProcessError as e:
        print(f"Error running grep: {e}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return []


def extract_executed_actions(log_file: str) -> List[Tuple[str, Dict[str, str]]]:
    """
    Extract executed actions from the test log.

    Returns list of tuples: (timestamp, action_dict)
    """
    try:
        # Grep for "Start of action" lines
        result = subprocess.run(
            ['grep', '-E', 'Start of action:.*Action -', log_file],
            capture_output=True,
            text=True,
            check=True
        )

        executed = []
        for line in result.stdout.strip().split('\n'):
            # Extract timestamp
            ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
            timestamp = ts_match.group(1) if ts_match else "Unknown"

            # Parse action details
            # Format: "action: N ~ Current list - X/Y; Action no. - Z; Action - ACTION; target - TARGET; value - VALUE;"
            action_match = re.search(
                r'action: (\d+) ~ Current list - (\d+)/(\d+); '
                r'Action no\. - (\d+); '
                r'Action - ([^;]+); '
                r'target - ([^;]*); '
                r'value - ([^;]*);',
                line
            )

            if action_match:
                executed.append((timestamp, {
                    'global_num': int(action_match.group(1)),
                    'list_num': int(action_match.group(2)),
                    'total_lists': int(action_match.group(3)),
                    'action_num': int(action_match.group(4)),
                    'action': action_match.group(5).strip(),
                    'target': action_match.group(6).strip(),
                    'value': action_match.group(7).strip()
                }))

        return executed

    except subprocess.CalledProcessError:
        print("No executed actions found in log file.", file=sys.stderr)
        return []
    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return []


def parse_actions(action_text: str) -> List[Dict[str, str]]:
    """
    Parse the action list text into structured actions.

    Format: action:target:value or sleep::value or check::number
    """
    actions = []

    # Split by spaces to get individual action items
    items = action_text.split()

    for item in items:
        parts = item.split(':')

        if len(parts) >= 2:
            action_name = parts[0]
            target = parts[1] if len(parts) > 1 else ""
            value = parts[2] if len(parts) > 2 else ""

            actions.append({
                'action': action_name,
                'target': target,
                'value': value
            })

    return actions


def format_action_list_compact(timestamp: str, actions: List[Dict[str, str]]) -> str:
    """Format actions in compact list-by-list view."""

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Action List at {timestamp}")
    output.append(f"{'='*80}\n")

    list_num = 1
    current_list = []

    for idx, action in enumerate(actions):
        action_name = action['action']
        target = action['target']
        value = action['value']

        if action_name == 'check':
            # Output the current list
            if current_list:
                output.append(f"List {list_num} → check::{value}")
                output.append("-" * 60)
                for i, act_str in enumerate(current_list, 1):
                    output.append(f"  {i:2d}. {act_str}")
                output.append("")
                current_list = []
                list_num += 1
        else:
            # Build action string
            if action_name == 'sleep':
                act_str = f"sleep {value}s"
            else:
                target_str = f":{target}" if target else ""
                value_str = f" = {value}" if value else ""
                act_str = f"{action_name}{target_str}{value_str}"

            current_list.append(act_str)

    # Handle any remaining actions
    if current_list:
        output.append(f"List {list_num} (incomplete)")
        output.append("-" * 60)
        for i, act_str in enumerate(current_list, 1):
            output.append(f"  {i:2d}. {act_str}")

    return '\n'.join(output)


def format_executed_actions(executed: List[Tuple[str, Dict[str, str]]]) -> str:
    """Format executed actions grouped by list."""

    if not executed:
        return "No executed actions found."

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Executed Actions Timeline")
    output.append(f"{'='*80}\n")

    current_list = None

    for timestamp, action in executed:
        list_num = action['list_num']
        action_num = action['action_num']
        total_lists = action['total_lists']
        global_num = action['global_num']

        # New list detected
        if current_list != list_num:
            if current_list is not None:
                output.append("")
            output.append(f"List {list_num}/{total_lists}")
            output.append("-" * 60)
            current_list = list_num

        # Format action
        action_name = action['action']
        target = action['target']
        value = action['value']

        if action_name == 'sleep':
            desc = f"sleep {value}s"
        elif action_name == 'check':
            desc = f"CHECK::{value} ✓"
        else:
            target_str = f" [{target}]" if target else ""
            value_str = f" = {value}" if value else ""
            desc = f"{action_name}{target_str}{value_str}"

        output.append(f"  [{timestamp}] #{global_num:3d} (Act {action_num:2d}): {desc}")

    return '\n'.join(output)


def main():
    # Parse command line arguments
    log_file = '/tmp/debug/log.txt'
    show_executed = False
    filter_list = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('--help', '-h'):
            print_help()
        elif arg == '--executed':
            show_executed = True
        elif arg == '--list' and i + 1 < len(sys.argv):
            filter_list = int(sys.argv[i + 1])
            i += 1
        elif not arg.startswith('--'):
            log_file = arg
        i += 1

    print(f"Parsing actions from: {log_file}")
    mode_str = 'Executed actions' if show_executed else 'Declared action lists'
    if filter_list is not None:
        mode_str += f" (List {filter_list} only)"
    print(f"Mode: {mode_str}\n")

    if show_executed:
        # Extract and display executed actions
        executed = extract_executed_actions(log_file)

        if not executed:
            print("No executed actions found in log file.")
            return 1

        # Filter by list if requested
        if filter_list is not None:
            executed = [(ts, act) for ts, act in executed if act['list_num'] == filter_list]

        print(f"Found {len(executed)} executed action(s)\n")
        print(format_executed_actions(executed))

    else:
        # Extract and display declared action lists
        action_lists = extract_action_lists(log_file)

        if not action_lists:
            print("No action lists found in log file.")
            return 1

        print(f"Found {len(action_lists)} action list(s)\n")

        # Process and display each action list
        for timestamp, full_line, action_text in action_lists:
            actions = parse_actions(action_text)
            print(format_action_list_compact(timestamp, actions))

    return 0


if __name__ == '__main__':
    sys.exit(main())
