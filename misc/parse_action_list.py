#!/usr/bin/env python3
"""
Parse and display action lists from reg_vmrRedundancyRandomActions.tcl test logs.

Usage:
    ./parse_action_list.py [OPTIONS] [log_file]

Options:
    --executed         Show executed actions from test output instead of declared action lists
    --list N           Show only list N (use with --executed)
    --traffic          Show traffic validation stats after each CHECK action (use with --executed)
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

    # Show timeline with traffic validation stats
    ./parse_action_list.py /tmp/processed/log.txt --executed --traffic

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


def extract_traffic_stats(log_file: str) -> Dict[str, Dict[str, any]]:
    """
    Extract traffic validation stats from the log file.

    Returns dict keyed by timestamp with traffic stats.
    """
    traffic_data = {}

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i]

            # Look for traffic validation result
            if 'Minimum Expected:' in line and 'actual' in line:
                # Look backward for timestamp (it's on a previous line)
                timestamp = "Unknown"
                for j in range(max(0, i - 5), i):
                    ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', lines[j])
                    if ts_match:
                        timestamp = ts_match.group(1)

                # Extract validation result: "Minimum Expected: 40 (actual 210)"
                val_match = re.search(r'Minimum Expected:\s+(\d+)\s+\(actual\s+(\d+)\)', line)
                if val_match:
                    min_expected = int(val_match.group(1))
                    actual = int(val_match.group(2))

                    if timestamp not in traffic_data:
                        traffic_data[timestamp] = {}

                    traffic_data[timestamp]['sub_rx_validation'] = {
                        'expected': min_expected,
                        'actual': actual,
                        'passed': actual >= min_expected
                    }

            # Look for publisher client-side stats BEFORE validation (for delta)
            elif 'Publisher client-side stats before ValidateMessageStreamsAtObject:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                stats = {}
                stats_match = re.findall(r'\{(\w+)\s+([^\}]+)\}', line)
                for key, value in stats_match:
                    try:
                        stats[key] = int(value) if value.isdigit() else value
                    except ValueError:
                        stats[key] = value

                if timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                traffic_data[timestamp]['pub_stats_before'] = stats

            # Look for publisher client-side stats AFTER validation
            elif 'Publisher client-side stats after ValidateMessageStreamsAtObject:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                # Parse keyed list: {rc OK} {txMsgs 240} {txBytes 7571920} ...
                stats = {}
                stats_match = re.findall(r'\{(\w+)\s+([^\}]+)\}', line)
                for key, value in stats_match:
                    try:
                        stats[key] = int(value) if value.isdigit() else value
                    except ValueError:
                        stats[key] = value

                if timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                traffic_data[timestamp]['pub_stats_after'] = stats

            # Look for subscriber client-side stats AFTER validation
            elif 'Subscriber client-side stats after ValidateMessageStreamsAtObject:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                stats = {}
                stats_match = re.findall(r'\{(\w+)\s+([^\}]+)\}', line)
                for key, value in stats_match:
                    try:
                        stats[key] = int(value) if value.isdigit() else value
                    except ValueError:
                        stats[key] = value

                if timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                traffic_data[timestamp]['sub_stats_after'] = stats

            # Look for publisher broker-side stats
            elif 'Publisher client message-spool-stats after traffic validation:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                if timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                # Parse multiple publisher clients
                traffic_data[timestamp]['pub_broker_stats'] = []
                j = i + 1
                current_client_name = None
                current_stats = {}

                # Look ahead for multiple publisher clients
                while j < len(lines) and j < i + 5000:
                    # Stop when we hit subscriber stats
                    if 'Subscriber client message-spool-stats after traffic validation:' in lines[j]:
                        break

                    # Look for client name in the SEMP command
                    if 'P2: -name c_vmrRedundancyRandomActions_pub_' in lines[j]:
                        # Save previous client if any
                        if current_client_name and current_stats:
                            traffic_data[timestamp]['pub_broker_stats'].append({
                                'name': current_client_name,
                                **current_stats
                            })
                        # Start new client
                        name_match = re.search(r'P2: -name (c_vmrRedundancyRandomActions_pub_\d+)', lines[j])
                        if name_match:
                            current_client_name = name_match.group(1)
                            current_stats = {}

                    # Extract stats for current client
                    elif current_client_name:
                        if '<last-message-id-sent>' in lines[j]:
                            match = re.search(r'<last-message-id-sent>(\d+)</last-message-id-sent>', lines[j])
                            if match:
                                current_stats['last_msg_id'] = int(match.group(1))
                        elif '<window-size>' in lines[j] and 'window_size' not in current_stats:
                            match = re.search(r'<window-size>(\d+)</window-size>', lines[j])
                            if match:
                                current_stats['window_size'] = int(match.group(1))
                        elif '<guaranteed-messages>' in lines[j]:
                            match = re.search(r'<guaranteed-messages>(\d+)</guaranteed-messages>', lines[j])
                            if match:
                                current_stats['inflight'] = int(match.group(1))

                    j += 1

                # Save last client
                if current_client_name and current_stats:
                    traffic_data[timestamp]['pub_broker_stats'].append({
                        'name': current_client_name,
                        **current_stats
                    })

            # Look for subscriber broker-side stats
            elif 'Subscriber client message-spool-stats after traffic validation:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                if timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                # Parse multiple subscriber clients
                traffic_data[timestamp]['sub_broker_stats'] = []
                j = i + 1
                current_client_name = None
                current_stats = {}

                # Look ahead for multiple subscriber clients
                while j < len(lines) and j < i + 5000:
                    # Stop when we hit a different section
                    if 'Message-spool stats after traffic validation:' in lines[j]:
                        break

                    # Look for client name in the SEMP command
                    if 'P2: -name c_vmrRedundancyRandomActions_sub_' in lines[j]:
                        # Save previous client if any
                        if current_client_name and current_stats:
                            traffic_data[timestamp]['sub_broker_stats'].append({
                                'name': current_client_name,
                                **current_stats
                            })
                        # Start new client
                        name_match = re.search(r'P2: -name (c_vmrRedundancyRandomActions_sub_\d+)', lines[j])
                        if name_match:
                            current_client_name = name_match.group(1)
                            current_stats = {}

                    # Extract stats for current client
                    elif current_client_name:
                        if '<flow-id>' in lines[j] and 'flow_id' not in current_stats:
                            match = re.search(r'<flow-id>(\d+)</flow-id>', lines[j])
                            if match:
                                current_stats['flow_id'] = int(match.group(1))
                        elif '<used-window>' in lines[j]:
                            match = re.search(r'<used-window>(\d+)</used-window>', lines[j])
                            if match:
                                current_stats['used_window'] = int(match.group(1))
                        elif '<low-message-id-ack-pending>' in lines[j]:
                            match = re.search(r'<low-message-id-ack-pending>(\d+)</low-message-id-ack-pending>', lines[j])
                            if match:
                                current_stats['low_msg_id_pending'] = int(match.group(1))
                        elif '<high-message-id-ack-pending>' in lines[j]:
                            match = re.search(r'<high-message-id-ack-pending>(\d+)</high-message-id-ack-pending>', lines[j])
                            if match:
                                current_stats['high_msg_id_pending'] = int(match.group(1))
                        elif '<message-confirmed-delivered>' in lines[j]:
                            match = re.search(r'<message-confirmed-delivered>(\d+)</message-confirmed-delivered>', lines[j])
                            if match:
                                current_stats['confirmed_delivered'] = int(match.group(1))
                        elif '<window-closed>' in lines[j]:
                            match = re.search(r'<window-closed>(\d+)</window-closed>', lines[j])
                            if match:
                                current_stats['window_closed'] = int(match.group(1))

                    j += 1

                # Save last client
                if current_client_name and current_stats:
                    traffic_data[timestamp]['sub_broker_stats'].append({
                        'name': current_client_name,
                        **current_stats
                    })

            # Look for message-spool stats
            elif 'Message-spool stats after traffic validation:' in line:
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                timestamp = ts_match.group(1) if ts_match else "Unknown"

                # Look ahead for the XML response with stats
                j = i + 1
                spool_stats = {}
                while j < len(lines) and j < i + 300:
                    # Extract key message-spool stats from XML
                    if '<ingress-messages>' in lines[j] and 'ingress' not in spool_stats:
                        # Match only standalone <ingress-messages>, not compound tags
                        match = re.search(r'<ingress-messages>(\d+)</ingress-messages>', lines[j])
                        if match:
                            spool_stats['ingress'] = int(match.group(1))
                    elif '<egress-messages>' in lines[j] and 'egress' not in spool_stats:
                        # Match only standalone <egress-messages>
                        match = re.search(r'<egress-messages>(\d+)</egress-messages>', lines[j])
                        if match:
                            spool_stats['egress'] = int(match.group(1))
                    elif '<total-discarded-messages>' in lines[j]:
                        match = re.search(r'<total-discarded-messages>(\d+)</total-discarded-messages>', lines[j])
                        if match:
                            spool_stats['discards'] = int(match.group(1))

                    # Stop when we have all three values
                    if 'ingress' in spool_stats and 'egress' in spool_stats and 'discards' in spool_stats:
                        break

                    j += 1

                if spool_stats and timestamp not in traffic_data:
                    traffic_data[timestamp] = {}

                if spool_stats:
                    traffic_data[timestamp]['msg_spool'] = spool_stats

            i += 1

        # Post-process: merge "before" and "after" stats that are close together
        merged_data = {}
        timestamps = sorted(traffic_data.keys(), key=lambda t: tuple(map(int, t.split(':'))))

        for ts in timestamps:
            data = traffic_data[ts]

            # If this entry has "after" stats, it's a complete entry
            if 'pub_stats_after' in data or 'sub_stats_after' in data:
                # Look for a nearby "before" entry to merge
                ts_secs = sum(int(x) * (60 ** (2 - i)) for i, x in enumerate(ts.split(':')))
                for prev_ts in timestamps:
                    prev_secs = sum(int(x) * (60 ** (2 - i)) for i, x in enumerate(prev_ts.split(':')))
                    if abs(prev_secs - ts_secs) <= 5 and 'pub_stats_before' in traffic_data[prev_ts]:
                        # Merge the "before" stats into this entry
                        data['pub_stats_before'] = traffic_data[prev_ts]['pub_stats_before']
                        break

                merged_data[ts] = data

            # If this entry only has "before" stats, skip it (it will be merged elsewhere)
            elif 'pub_stats_before' in data:
                continue

            # Otherwise, keep it as is
            else:
                merged_data[ts] = data

        return merged_data

    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return {}


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


def deduplicate_executed_actions(executed: List[Tuple[str, Dict[str, str]]]) -> List[Tuple[str, Dict[str, str]]]:
    """
    Deduplicate executed actions by global action number.

    The test framework logs each action multiple times to different log facilities.
    Keep only one entry per global action number, preferring entries with actual timestamps.
    """
    seen = {}

    for timestamp, action in executed:
        global_num = action['global_num']

        if global_num not in seen:
            seen[global_num] = (timestamp, action)
        else:
            # If current entry has a real timestamp and existing doesn't, replace it
            existing_ts, existing_action = seen[global_num]
            if timestamp != "Unknown" and existing_ts == "Unknown":
                seen[global_num] = (timestamp, action)

    # Return in original order (sorted by global action number)
    return [seen[key] for key in sorted(seen.keys())]


def format_executed_actions(executed: List[Tuple[str, Dict[str, str]]],
                            traffic_data: Dict[str, Dict[str, any]] = None) -> str:
    """Format executed actions grouped by list."""

    if not executed:
        return "No executed actions found."

    # Deduplicate entries
    executed = deduplicate_executed_actions(executed)

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

        # Add traffic stats after CHECK actions if available
        if action_name == 'check' and traffic_data:
            # Look for traffic stats within a few seconds of this timestamp
            traffic_stats = find_traffic_stats_near_timestamp(timestamp, traffic_data)
            if traffic_stats:
                output.append("")
                output.append(format_traffic_stats(traffic_stats))

    return '\n'.join(output)


def find_traffic_stats_near_timestamp(check_timestamp: str,
                                       traffic_data: Dict[str, Dict[str, any]],
                                       window_seconds: int = 30) -> Dict[str, any]:
    """
    Find traffic stats near the given timestamp (within window_seconds).

    Returns the traffic stats dict or None if not found.
    """
    if not traffic_data:
        return None

    # Parse check timestamp to seconds
    try:
        h, m, s = map(int, check_timestamp.split(':'))
        check_secs = h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        return None

    # Find closest traffic stats within window
    closest_stats = None
    min_diff = window_seconds + 1

    for ts, stats in traffic_data.items():
        try:
            h, m, s = map(int, ts.split(':'))
            traffic_secs = h * 3600 + m * 60 + s

            diff = abs(traffic_secs - check_secs)
            if diff < min_diff and diff <= window_seconds:
                min_diff = diff
                closest_stats = stats.copy()
                closest_stats['timestamp'] = ts
        except (ValueError, AttributeError):
            continue

    return closest_stats


def format_traffic_stats(stats: Dict[str, any]) -> str:
    """Format traffic stats for display."""
    lines = []
    ts = stats.get('timestamp', 'Unknown')
    lines.append(f"    Traffic Validation ({ts}):")

    # Subscriber RX validation
    if 'sub_rx_validation' in stats:
        val = stats['sub_rx_validation']
        status = '✓' if val['passed'] else '✗'
        lines.append(f"      Subscriber RX: {val['actual']} msgs "
                     f"(expected ≥{val['expected']}) {status}")

    # Publisher client-side stats (aggregate with delta)
    if 'pub_stats_after' in stats:
        pub_after = stats['pub_stats_after']
        pub_before = stats.get('pub_stats_before', {})
        tx_msgs_after = pub_after.get('txMsgs', 0)
        tx_msgs_before = pub_before.get('txMsgs', 0)
        delta = tx_msgs_after - tx_msgs_before
        tx_rate = pub_after.get('txMsgRate', 0.0)
        lines.append(f"      Pub Client:  txMsgs={tx_msgs_after} (Δ{delta}), "
                     f"txRate={tx_rate} msg/s")

    # Publisher broker-side stats (per-client and aggregate)
    if 'pub_broker_stats' in stats and isinstance(stats['pub_broker_stats'], list):
        pub_clients = stats['pub_broker_stats']
        if len(pub_clients) > 0:
            lines.append(f"      Publishers:  {len(pub_clients)} client(s)")
            total_inflight = 0
            for pub in pub_clients:
                name = pub.get('name', 'unknown')
                short_name = name.replace('c_vmrRedundancyRandomActions_pub_', 'pub_')
                last_msg_id = pub.get('last_msg_id', 0)
                window_size = pub.get('window_size', 0)
                inflight = pub.get('inflight', 0)
                total_inflight += inflight
                lines.append(f"        {short_name}: lastMsgId={last_msg_id}, "
                             f"window={window_size}, inflight={inflight}")
            lines.append(f"        TOTAL: inflight={total_inflight}")

    # Subscriber client-side stats (aggregate with delta)
    if 'sub_stats_after' in stats:
        sub_after = stats['sub_stats_after']
        rx_msgs = sub_after.get('rxMsgs', 0)
        rx_rate = sub_after.get('rxMsgRate', 0.0)
        lines.append(f"      Sub Client:  rxMsgs={rx_msgs}, rxRate={rx_rate} msg/s")

    # Subscriber broker-side stats (per-client and aggregate)
    if 'sub_broker_stats' in stats and isinstance(stats['sub_broker_stats'], list):
        sub_clients = stats['sub_broker_stats']
        if len(sub_clients) > 0:
            lines.append(f"      Subscribers: {len(sub_clients)} client(s)")
            total_confirmed = 0
            total_window_closed = 0
            for sub in sub_clients:
                name = sub.get('name', 'unknown')
                short_name = name.replace('c_vmrRedundancyRandomActions_sub_', 'sub_')
                flow_id = sub.get('flow_id', 0)
                used_window = sub.get('used_window', 0)
                low_msg_id = sub.get('low_msg_id_pending', 0)
                high_msg_id = sub.get('high_msg_id_pending', 0)
                confirmed = sub.get('confirmed_delivered', 0)
                window_closed = sub.get('window_closed', 0)
                total_confirmed += confirmed
                total_window_closed += window_closed
                lines.append(f"        {short_name}: flowId={flow_id}, usedWindow={used_window}, "
                             f"ackPending={low_msg_id}-{high_msg_id}")
                lines.append(f"                  confirmed={confirmed}, windowClosed={window_closed}")
            lines.append(f"        TOTAL: confirmed={total_confirmed}, "
                         f"windowClosed={total_window_closed}")

    # Message-spool stats
    if 'msg_spool' in stats:
        spool = stats['msg_spool']
        ingress = spool.get('ingress', 0)
        egress = spool.get('egress', 0)
        discards = spool.get('discards', 0)
        lines.append(f"      Msg Spool:   ingress={ingress}, egress={egress}, "
                     f"discards={discards}")

    return '\n'.join(lines)


def main():
    # Parse command line arguments
    log_file = '/tmp/debug/log.txt'
    show_executed = False
    show_traffic = False
    filter_list = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('--help', '-h'):
            print_help()
        elif arg == '--executed':
            show_executed = True
        elif arg == '--traffic':
            show_traffic = True
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
    if show_traffic:
        mode_str += " with traffic stats"
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

        # Extract traffic stats if requested
        traffic_data = None
        if show_traffic:
            print("Extracting traffic validation stats...\n")
            traffic_data = extract_traffic_stats(log_file)
            if traffic_data:
                print(f"Found {len(traffic_data)} traffic validation entries\n")

        print(format_executed_actions(executed, traffic_data))

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
