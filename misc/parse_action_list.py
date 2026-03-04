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
from typing import List, Tuple, Dict, Optional
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


def _parse_keyed_list(line: str) -> Dict[str, any]:
    """Parse a Tcl keyed list like {rc OK} {txMsgs 240} {txMsgRate 99.17}."""
    result = {}
    for key, value in re.findall(r'\{(\w+)\s+([^\}]+)\}', line):
        try:
            result[key] = float(value) if '.' in value else int(value)
        except ValueError:
            result[key] = value
    return result


def extract_traffic_blocks(log_file: str) -> List[Dict]:
    """
    Extract traffic validation blocks from the log file.

    Each block corresponds to one verifyHaStateAndTraffic call, anchored at
    '=== Debug info before traffic validation ==='.

    Stats are always reset just before the block runs, so SDK "after" values
    are direct deltas (no subtraction needed).  Per-publisher broker
    guaranteed-messages after the clear equals msgs sent during the interval.

    Returns a list of block dicts containing:
      anchor_ts, pub_stats_after, sub_stats_after, validation,
      msg_spool, pub_clients_after, sub_clients_after
    """
    blocks = []
    current_block = None
    section = None
    cur_pub = None
    cur_sub = None

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()

        for line in lines:
            # New block starts at this marker
            if 'Debug info before traffic validation' in line:
                if current_block is not None:
                    blocks.append(current_block)
                ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                current_block = {
                    'anchor_ts': ts_match.group(1) if ts_match else 'Unknown',
                    'pub_clients_after': {},
                    'sub_clients_after': {},
                }
                section = None
                cur_pub = None
                cur_sub = None
                continue

            if current_block is None:
                continue

            # Single-line SDK stats (highest priority — check before section routing)
            if 'Publisher client-side stats after ValidateMessageStreamsAtObject:' in line:
                current_block['pub_stats_after'] = _parse_keyed_list(line)
                section = None
                continue
            if 'Subscriber client-side stats after ValidateMessageStreamsAtObject:' in line:
                current_block['sub_stats_after'] = _parse_keyed_list(line)
                section = None
                continue

            # Validation result (first occurrence per block)
            if 'Minimum Expected:' in line and 'validation' not in current_block:
                m = re.search(r'Minimum Expected:\s+(\d+)\s+\(actual\s+(\d+)\)', line)
                if m:
                    exp, act = int(m.group(1)), int(m.group(2))
                    current_block['validation'] = {
                        'expected': exp,
                        'actual': act,
                        'passed': act >= exp,
                    }
                continue

            # Section markers
            if 'Message-spool stats after traffic validation:' in line:
                section = 'spool'
                current_block.setdefault('msg_spool', {})
                continue
            if 'Publisher client message-spool-stats after traffic validation:' in line:
                section = 'pub_broker'
                cur_pub = None
                continue
            if 'Subscriber client message-spool-stats after traffic validation:' in line:
                section = 'sub_broker'
                cur_sub = None
                continue
            if 'Debug info after traffic validation' in line:
                section = None
                continue

            # Section-specific XML parsing
            if section == 'spool':
                for tag, key in [('ingress-messages', 'ingress'),
                                  ('egress-messages', 'egress'),
                                  ('total-discarded-messages', 'discards')]:
                    m = re.search(fr'<{tag}>(\d+)</{tag}>', line)
                    if m:
                        current_block['msg_spool'][key] = int(m.group(1))
                        break

            elif section == 'pub_broker':
                m = re.search(r'P2: -name (c_vmrRedundancyRandomActions_pub_\w+)', line)
                if m:
                    cur_pub = m.group(1)
                    current_block['pub_clients_after'].setdefault(cur_pub, {})
                elif cur_pub:
                    for tag, key in [('last-message-id-sent', 'last_msg_id'),
                                     ('guaranteed-messages', 'sent')]:
                        m = re.search(fr'<{tag}>(\d+)</{tag}>', line)
                        if m:
                            current_block['pub_clients_after'][cur_pub][key] = int(m.group(1))
                            break

            elif section == 'sub_broker':
                m = re.search(r'P2: -name (c_vmrRedundancyRandomActions_sub_\w+)', line)
                if m:
                    cur_sub = m.group(1)
                    current_block['sub_clients_after'].setdefault(cur_sub, {})
                elif cur_sub:
                    m = re.search(
                        r'<message-confirmed-delivered>(\d+)</message-confirmed-delivered>',
                        line)
                    if m:
                        current_block['sub_clients_after'][cur_sub][
                            'confirmed_delivered'] = int(m.group(1))

        if current_block is not None:
            blocks.append(current_block)

    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)

    return blocks


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


def extract_end_time_entries(log_file: str) -> List[Tuple[str, int]]:
    """
    Extract end action entries as (timestamp, global_num) pairs in log order.
    """
    try:
        result = subprocess.run(
            ['grep', '-E', 'End of action:.*Action -', log_file],
            capture_output=True,
            text=True,
            check=True
        )

        entries = []
        for line in result.stdout.strip().split('\n'):
            ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
            if not ts_match:
                continue
            action_match = re.search(r'action: (\d+) ~', line)
            if action_match:
                entries.append((ts_match.group(1), int(action_match.group(1))))

        return entries

    except subprocess.CalledProcessError:
        return []
    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return []


def split_into_runs(
        executed: List[Tuple[str, Dict[str, str]]]
) -> List[List[Tuple[str, Dict[str, str]]]]:
    """
    Split flat list of executed action entries into individual test runs.

    A new run is detected when global_num resets (decreases significantly),
    which happens when the test completes all lists and starts again.
    The threshold of 10 is safely larger than any fan-out reordering but
    much smaller than the typical action count per run (~200).
    """
    runs: List[List] = []
    current_run: List = []
    run_max = 0

    for entry in executed:
        global_num = entry[1]['global_num']
        if current_run and global_num < run_max - 10:
            runs.append(current_run)
            current_run = []
            run_max = 0
        current_run.append(entry)
        if global_num > run_max:
            run_max = global_num

    if current_run:
        runs.append(current_run)

    return runs


def split_end_times_into_runs(
        entries: List[Tuple[str, int]]
) -> List[Dict[int, Tuple[str, str]]]:
    """
    Split end time entries into runs and group by global_num within each run.

    Uses the same global_num-reset heuristic as split_into_runs.
    Returns list of dicts (one per run): {global_num: (end_first, end_last)}
    """
    run_buckets: List[List[Tuple[str, int]]] = []
    current_bucket: List[Tuple[str, int]] = []
    run_max = 0

    for ts, global_num in entries:
        if current_bucket and global_num < run_max - 10:
            run_buckets.append(current_bucket)
            current_bucket = []
            run_max = 0
        current_bucket.append((ts, global_num))
        if global_num > run_max:
            run_max = global_num

    if current_bucket:
        run_buckets.append(current_bucket)

    result = []
    for bucket in run_buckets:
        grouped: Dict[int, List[str]] = {}
        for ts, global_num in bucket:
            if global_num not in grouped:
                grouped[global_num] = [ts, ts]
            else:
                entry = grouped[global_num]
                if ts_to_seconds(ts) < ts_to_seconds(entry[0]):
                    entry[0] = ts
                if ts_to_seconds(ts) > ts_to_seconds(entry[1]):
                    entry[1] = ts
        result.append({k: (v[0], v[1]) for k, v in grouped.items()})

    return result


def ts_to_seconds(ts: str) -> int:
    """Convert HH:MM:SS timestamp to seconds since midnight."""
    h, m, s = map(int, ts.split(':'))
    return h * 3600 + m * 60 + s


def format_duration(start_ts: str, end_ts: str) -> str:
    """Format the duration between two HH:MM:SS timestamps."""
    secs = ts_to_seconds(end_ts) - ts_to_seconds(start_ts)
    if secs < 0:
        secs += 86400  # handle midnight rollover
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"


def group_run_entries(
        run: List[Tuple[str, Dict[str, str]]]
) -> List[Tuple[str, str, Dict[str, str]]]:
    """
    Group a single run's entries by global_num, tracking first/last start times.

    Each action is logged many times (once per router × log facility). Tracking
    first and last captures the fan-out spread, which is typically a few seconds.

    Returns list of tuples: (start_first, start_last, action_dict)
    """
    seen: Dict[int, List] = {}

    for timestamp, action in run:
        global_num = action['global_num']

        if global_num not in seen:
            seen[global_num] = [timestamp, timestamp, action]
        elif timestamp != "Unknown":
            entry = seen[global_num]
            if entry[0] == "Unknown":
                entry[0] = timestamp
                entry[1] = timestamp
            else:
                if ts_to_seconds(timestamp) < ts_to_seconds(entry[0]):
                    entry[0] = timestamp
                if ts_to_seconds(timestamp) > ts_to_seconds(entry[1]):
                    entry[1] = timestamp

    return [(e[0], e[1], e[2]) for e in (seen[k] for k in sorted(seen.keys()))]


def format_executed_actions(
        executed: List[Tuple[str, Dict[str, str]]],
        traffic_blocks: List[Dict] = None,
        end_times_per_run: List[Dict[int, Tuple[str, str]]] = None) -> str:
    """Format executed actions grouped by list and run."""

    if not executed:
        return "No executed actions found."

    runs = split_into_runs(executed)

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Executed Actions Timeline ({len(runs)} run(s))")
    output.append(f"{'='*80}\n")

    # Pre-collect check start times (in run/action order) for range-based matching
    all_check_starts = []
    if traffic_blocks:
        for run in runs:
            for start_first, _, action in group_run_entries(run):
                if action['action'] == 'check':
                    all_check_starts.append(start_first)

    check_idx = 0

    for run_idx, run in enumerate(runs, 1):
        run_end_times = (end_times_per_run[run_idx - 1]
                         if end_times_per_run and run_idx - 1 < len(end_times_per_run)
                         else {})
        grouped = group_run_entries(run)
        current_list = None

        for start_first, start_last, action in grouped:
            list_num = action['list_num']
            action_num = action['action_num']
            total_lists = action['total_lists']
            global_num = action['global_num']

            if current_list != list_num:
                if current_list is not None:
                    output.append("")
                output.append(f"List {list_num}/{total_lists} [{run_idx}]")
                output.append("-" * 60)
                current_list = list_num

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

            start_str = (f"{start_first}..{start_last}"
                         if start_first != start_last else start_first)

            end = run_end_times.get(global_num)
            if end:
                end_first, end_last = end
                end_str = (f"{end_first}..{end_last}"
                           if end_first != end_last else end_first)
                duration = format_duration(start_first, end_first)
                time_str = f"{start_str} → {end_str} ({duration})"
            else:
                time_str = start_str
            output.append(
                f"  [{time_str}] #{global_num:3d} (Act {action_num:2d}): {desc}"
            )

            if action_name == 'check' and traffic_blocks:
                next_ts = (all_check_starts[check_idx + 1]
                           if check_idx + 1 < len(all_check_starts)
                           else None)
                blocks = find_traffic_blocks_for_check(
                    start_first, next_ts, traffic_blocks
                )
                for block in blocks:
                    output.append("")
                    output.append(format_traffic_block(block))
                check_idx += 1

        if run_idx < len(runs):
            output.append("")

    return '\n'.join(output)


def find_traffic_blocks_for_check(
        check_ts: str,
        next_check_ts: Optional[str],
        traffic_blocks: List[Dict],
) -> List[Dict]:
    """
    Return traffic blocks whose anchor_ts falls in [check_ts, next_check_ts).

    Each check action owns the blocks that started after it began and before
    the next check started.  This is reliable because verifyHaStateAndTraffic
    is called from within the check action and checks are spaced minutes apart.
    """
    check_secs = ts_to_seconds(check_ts)
    next_secs = ts_to_seconds(next_check_ts) if next_check_ts else 86400
    return [b for b in traffic_blocks
            if b['anchor_ts'] != 'Unknown'
            and check_secs <= ts_to_seconds(b['anchor_ts']) < next_secs]


def format_traffic_block(block: Dict) -> str:
    """Format one traffic validation block (one verifyHaStateAndTraffic call)."""
    lines = []
    ts = block.get('anchor_ts', 'Unknown')
    lines.append(f"    Traffic Validation ({ts}):")

    # Validation result
    if 'validation' in block:
        val = block['validation']
        status = '✓' if val['passed'] else '✗'
        lines.append(f"      Validation: expected≥{val['expected']}, "
                     f"actual={val['actual']} {status}")

    # Publisher SDK stats — txMsgs is a direct delta (stats reset before block)
    if 'pub_stats_after' in block:
        pub = block['pub_stats_after']
        lines.append(f"      Pub SDK:    txMsgs={pub.get('txMsgs', 0)}, "
                     f"txRate={pub.get('txMsgRate', 0.0)} msg/s")

    # Subscriber SDK stats — rxMsgs is a direct delta (stats reset before block)
    if 'sub_stats_after' in block:
        sub = block['sub_stats_after']
        lines.append(f"      Sub SDK:    rxMsgs={sub.get('rxMsgs', 0)}, "
                     f"rxRate={sub.get('rxMsgRate', 0.0)} msg/s")

    # Per-publisher broker stats — guaranteed-messages = msgs sent since clear
    if block.get('pub_clients_after'):
        clients = block['pub_clients_after']
        total = sum(c.get('sent', 0) for c in clients.values())
        lines.append(f"      Pub broker: {len(clients)} client(s), total_sent={total}")
        for name, stats in sorted(clients.items()):
            short = name.replace('c_vmrRedundancyRandomActions_pub_', 'pub_')
            lines.append(f"        {short}: sent={stats.get('sent', 0)}, "
                         f"last_id={stats.get('last_msg_id', 0)}")

    # Message-spool stats
    if 'msg_spool' in block:
        spool = block['msg_spool']
        lines.append(f"      Spool:      ingress={spool.get('ingress', 0)}, "
                     f"egress={spool.get('egress', 0)}, "
                     f"discards={spool.get('discards', 0)}")

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

        # Extract traffic blocks if requested
        traffic_blocks = None
        if show_traffic:
            print("Extracting traffic validation blocks...\n")
            traffic_blocks = extract_traffic_blocks(log_file)
            if traffic_blocks:
                print(f"Found {len(traffic_blocks)} traffic validation block(s)\n")

        end_times_per_run = split_end_times_into_runs(
            extract_end_time_entries(log_file)
        )
        print(format_executed_actions(executed, traffic_blocks, end_times_per_run))

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
