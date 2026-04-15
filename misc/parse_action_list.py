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
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


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
            ["grep", "Action list", log_file, "-A", "2"],
            capture_output=True,
            text=True,
            check=True,
        )

        lines = result.stdout.strip().split("\n")
        action_lists = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Look for timestamp line with "Action list:"
            if "Action list:" in line:
                # Extract timestamp [HH:MM:SS]
                timestamp_match = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
                timestamp = timestamp_match.group(1) if timestamp_match else "Unknown"

                # Skip the "------------" separator line
                i += 1
                if i < len(lines) and "------------" in lines[i]:
                    i += 1

                # Get the action list content (may span multiple lines until next separator)
                action_text = ""
                while i < len(lines) and lines[i] != "--":
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
            ["grep", "-E", "Start of action:.*Action -", log_file],
            capture_output=True,
            text=True,
            check=True,
        )

        executed = []
        for line in result.stdout.strip().split("\n"):
            # Extract timestamp
            ts_match = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
            timestamp = ts_match.group(1) if ts_match else "Unknown"

            # Parse action details
            # Format: "action: N ~ Current list - X/Y; Action no. - Z; Action - ACTION; target - TARGET; value - VALUE;"
            action_match = re.search(
                r"action: (\d+) ~ Current list - (\d+)/(\d+); "
                r"Action no\. - (\d+); "
                r"Action - ([^;]+); "
                r"target - ([^;]*); "
                r"value - ([^;]*);",
                line,
            )

            if action_match:
                executed.append(
                    (
                        timestamp,
                        {
                            "global_num": int(action_match.group(1)),
                            "list_num": int(action_match.group(2)),
                            "total_lists": int(action_match.group(3)),
                            "action_num": int(action_match.group(4)),
                            "action": action_match.group(5).strip(),
                            "target": action_match.group(6).strip(),
                            "value": action_match.group(7).strip(),
                        },
                    )
                )

        return executed

    except subprocess.CalledProcessError:
        print("No executed actions found in log file.", file=sys.stderr)
        return []
    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return []


def _extract_ts(line: str) -> str:
    """Extract HH:MM:SS timestamp from a log line."""
    m = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
    return m.group(1) if m else "Unknown"


def _parse_tcl_kv(line: str) -> Dict:
    """Parse Tcl-style {key value} pairs from a line into a typed dict."""
    result = {}
    for key, val in re.findall(r"\{(\w+)\s+([^}]+)\}", line):
        val = val.strip()
        try:
            result[key] = int(val)
        except ValueError:
            try:
                result[key] = float(val)
            except ValueError:
                result[key] = val
    return result


def _parse_element_flat(elem: ET.Element) -> Dict[str, Any]:
    """Return a flat {tag: value} dict for the direct children of an XML element."""
    result = {}
    for child in elem:
        text = (child.text or "").strip()
        try:
            result[child.tag] = int(text)
        except ValueError:
            result[child.tag] = text
    return result


def _parse_client_spool_stats(xml_lines: List[str]) -> Optional[Dict]:
    """
    Parse message-spool-stats from an RPC-REPLY XML captured as a list of lines.

    Returns a dict with keys:
      ingress_flows: list of flat dicts for each ingress-flow-stat element
      egress_flows:  list of flat dicts for each egress-flow-stat element
      qendpt_bind:   flat dict for qendpt-bind-stats
      pub_open:      flat dict for publisher-open-stats
    Returns None if the XML cannot be parsed or the expected element is missing.
    """
    try:
        root = ET.fromstring("\n".join(xml_lines))
    except ET.ParseError:
        return None

    spool = root.find("./rpc/show/client/client/message-spool-stats")
    if spool is None:
        return None

    result: Dict[str, Any] = {}

    ingress = spool.find("ingress-flow-stats")
    if ingress is not None:
        result["ingress_flows"] = [
            _parse_element_flat(f) for f in ingress.findall("ingress-flow-stat")
        ]

    egress = spool.find("egress-flow-stats")
    if egress is not None:
        result["egress_flows"] = [
            _parse_element_flat(f) for f in egress.findall("egress-flow-stat")
        ]

    qb = spool.find("qendpt-bind-stats")
    if qb is not None:
        result["qendpt_bind"] = _parse_element_flat(qb)

    po = spool.find("publisher-open-stats")
    if po is not None:
        result["pub_open"] = _parse_element_flat(po)

    return result


def _flatten_element(elem: ET.Element, prefix: str = "") -> Dict[str, Any]:
    """
    Recursively flatten an XML element's children into a dotted-key dict.

    Leaf elements (no children) are stored as {tag: value}; elements with
    children are expanded as {parent.child: value, ...}.
    """
    result = {}
    for child in elem:
        key = f"{prefix}{child.tag}"
        if len(child):
            result.update(_flatten_element(child, f"{key}."))
        else:
            text = (child.text or "").strip()
            try:
                result[key] = int(text)
            except ValueError:
                result[key] = text
    return result


def _parse_spool_stats_flat(xml_lines: List[str]) -> Optional[Dict[str, Any]]:
    """
    Parse global message-spool-stats from an RPC-REPLY XML captured as lines.

    Returns a flat {key: value} dict; nested elements are expanded with dotted
    keys (e.g. xa-transactions-success-operations.recover).
    Returns None if the XML cannot be parsed or the expected element is missing.
    """
    try:
        root = ET.fromstring("\n".join(xml_lines))
    except ET.ParseError:
        return None
    spool = root.find("./rpc/show/message-spool/message-spool-stats")
    if spool is None:
        return None
    return _flatten_element(spool)


def _parse_queue_info(xml_lines: List[str]) -> Optional[Dict[str, Any]]:
    """
    Parse queue info from an RPC-REPLY XML captured as lines.

    Extracts direct children of the <info> element only; nested elements
    (event, clients) are skipped.
    Returns None if the XML cannot be parsed or the expected element is missing.
    """
    try:
        root = ET.fromstring("\n".join(xml_lines))
    except ET.ParseError:
        return None
    info = root.find("./rpc/show/queue/queues/queue/info")
    if info is None:
        return None
    return _parse_element_flat(info)


# Fields used as sub-header identifiers in flow-stat tables, not data rows.
_INGRESS_FLOW_IDENTS = frozenset({"flow-name", "flow-id", "publisher-id"})
_EGRESS_FLOW_IDENTS = frozenset({"flow-id"})


def _handle_result_line(
    line: str,
    block: Dict,
    phase: Optional[str],
    section: Optional[str],
) -> Optional[str]:
    """
    Process a [RESULT] log line and return the resulting section value.

    Side effect: updates block pub_side or sub_side for SDK-stats lines.
    Returns the new section; returns the existing section if the line is
    not a recognised stats-section anchor.
    """
    if "Publisher client message-spool-stats:" in line:
        return "pub"
    if "Subscriber client message-spool-stats:" in line:
        return "sub"
    if "Global message-spool stats:" in line:
        return "global"
    if "Publisher client-side stats:" in line and phase:
        block["pub_side"][phase] = _parse_tcl_kv(line)
        return None
    if "Subscriber client-side stats:" in line and phase:
        block["sub_side"][phase] = _parse_tcl_kv(line)
        return None
    if re.search(r"\bVPN \S+ message-spool stats:", line):
        return "vpn_spool"
    if re.search(r"\bQueue \S+ stats:", line):
        return "queue"
    return section


def _store_xml_result(
    block: Dict, xml_lines: List[str], section: str, client: str, phase: str
) -> None:
    """Store parsed XML result into the appropriate section of a traffic block."""
    if section in ("pub", "sub"):
        stats = _parse_client_spool_stats(xml_lines)
        if stats is not None:
            store = block["pub_clients"] if section == "pub" else block["sub_clients"]
            store.setdefault(client, {})[phase] = stats
    elif section == "global":
        stats = _parse_spool_stats_flat(xml_lines)
        if stats is not None:
            block["global_spools"].setdefault(client, {})[phase] = stats
    elif section == "vpn_spool":
        stats = _parse_spool_stats_flat(xml_lines)
        if stats is not None:
            block["vpn_spools"].setdefault(client, {})[phase] = stats
    elif section == "queue":
        stats = _parse_queue_info(xml_lines)
        if stats is not None:
            block["queues"].setdefault(client, {})[phase] = stats


def extract_traffic_blocks(log_file: str) -> List[Dict]:
    """
    Extract prior/after stat dump pairs from the log file.

    Each pair brackets one ValidateMessageStreamsAtObject call and contains:
      prior_ts:    timestamp of "Logging stats prior to traffic test."
      after_ts:    timestamp of "Logging stats after traffic test."
      pub_clients: {client_name: {'prior': stats, 'after': stats}}
      sub_clients: {client_name: {'prior': stats, 'after': stats}}

    where stats has keys: ingress_flows, egress_flows, qendpt_bind, pub_open.
    """
    blocks: List[Dict] = []
    block: Optional[Dict] = None
    phase: Optional[str] = None  # 'prior' or 'after'
    section: Optional[str] = None  # 'pub', 'sub', 'global', 'vpn_spool', 'queue'
    awaiting_name = False
    current_client: Optional[str] = None
    pending_router: Optional[str] = None
    in_xml = False
    xml_lines: List[str] = []

    try:
        with open(log_file) as f:
            for raw in f:
                line = raw.rstrip("\n")

                if "Logging stats prior to traffic test" in line:
                    if block is not None:
                        blocks.append(block)
                    block = {
                        "prior_ts": _extract_ts(line),
                        "after_ts": None,
                        "pub_clients": {},
                        "sub_clients": {},
                        "global_spools": {},
                        "vpn_spools": {},
                        "queues": {},
                        "pub_side": {},
                        "sub_side": {},
                    }
                    phase = "prior"
                    section = None
                    awaiting_name = False
                    current_client = None
                    pending_router = None
                    in_xml = False
                    xml_lines = []
                    continue

                if block is None:
                    continue

                if "Logging stats after traffic test" in line:
                    phase = "after"
                    section = None
                    awaiting_name = False
                    current_client = None
                    pending_router = None
                    in_xml = False
                    xml_lines = []
                    block["after_ts"] = _extract_ts(line)
                    continue

                if in_xml:
                    xml_lines.append(line)
                    if "</rpc-reply>" in line:
                        in_xml = False
                        if (
                            current_client
                            and section
                            in ("pub", "sub", "global", "vpn_spool", "queue")
                            and phase
                        ):
                            _store_xml_result(
                                block, xml_lines, section, current_client, phase
                            )
                        xml_lines = []
                        current_client = None
                    continue

                if "[RESULT]" in line:
                    section = _handle_result_line(line, block, phase, section)
                    awaiting_name = False
                    pending_router = None
                    continue

                if section in ("pub", "sub"):
                    if "::L1::Show::Client] Method params:" in line:
                        awaiting_name = True
                        continue
                    if awaiting_name and "P2: -name" in line:
                        m = re.search(r"P2: -name (\S+)", line)
                        if m:
                            current_client = m.group(1)
                        awaiting_name = False
                        continue
                    if current_client and "RPC-REPLY:" in line:
                        in_xml = True
                        xml_lines = []
                        remainder = line[line.index("RPC-REPLY:") + 10 :].strip()
                        if remainder:
                            xml_lines.append(remainder)
                elif section == "global":
                    if "::L1::Show::MessageSpool] Method params:" in line:
                        awaiting_name = True
                        continue
                    if awaiting_name and "P1: -rtrObj" in line:
                        m = re.search(
                            r"P1: -rtrObj (?:::RtrManager::)?router_(\S+)", line
                        )
                        if m:
                            current_client = m.group(1)
                        awaiting_name = False
                        continue
                    if current_client and "RPC-REPLY:" in line:
                        in_xml = True
                        xml_lines = []
                        remainder = line[line.index("RPC-REPLY:") + 10 :].strip()
                        if remainder:
                            xml_lines.append(remainder)
                elif section == "vpn_spool":
                    if "::L1::Show::MessageSpool] Method params:" in line:
                        awaiting_name = True
                        pending_router = None
                        continue
                    if awaiting_name and "P1: -rtrObj" in line:
                        m = re.search(
                            r"P1: -rtrObj (?:::RtrManager::)?router_(\S+)", line
                        )
                        if m:
                            pending_router = m.group(1)
                        continue
                    if awaiting_name and pending_router and "P3: -msgVpn" in line:
                        m = re.search(r"P3: -msgVpn (\S+)", line)
                        if m:
                            current_client = f"{pending_router}:{m.group(1)}"
                        awaiting_name = False
                        continue
                    if current_client and "RPC-REPLY:" in line:
                        in_xml = True
                        xml_lines = []
                        remainder = line[line.index("RPC-REPLY:") + 10 :].strip()
                        if remainder:
                            xml_lines.append(remainder)
                elif section == "queue":
                    if "::L1::Show::Queue] Method params:" in line:
                        awaiting_name = True
                        pending_router = None
                        continue
                    if awaiting_name and "P1: -rtrObj" in line:
                        m = re.search(
                            r"P1: -rtrObj (?:::RtrManager::)?router_(\S+)", line
                        )
                        if m:
                            pending_router = m.group(1)
                        continue
                    if awaiting_name and pending_router and "P2: -name" in line:
                        m = re.search(r"P2: -name (\S+)", line)
                        if m:
                            current_client = f"{pending_router}:{m.group(1)}"
                        awaiting_name = False
                        continue
                    if current_client and "RPC-REPLY:" in line:
                        in_xml = True
                        xml_lines = []
                        remainder = line[line.index("RPC-REPLY:") + 10 :].strip()
                        if remainder:
                            xml_lines.append(remainder)

    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)

    if block is not None:
        blocks.append(block)

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
        parts = item.split(":")

        if len(parts) >= 2:
            action_name = parts[0]
            target = parts[1] if len(parts) > 1 else ""
            value = parts[2] if len(parts) > 2 else ""

            actions.append({"action": action_name, "target": target, "value": value})

    return actions


def format_action_list_compact(timestamp: str, actions: List[Dict[str, str]]) -> str:
    """Format actions in compact list-by-list view."""

    output = []
    output.append(f"\n{'=' * 80}")
    output.append(f"Action List at {timestamp}")
    output.append(f"{'=' * 80}\n")

    list_num = 1
    current_list = []

    for idx, action in enumerate(actions):
        action_name = action["action"]
        target = action["target"]
        value = action["value"]

        if action_name == "check":
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
            if action_name == "sleep":
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

    return "\n".join(output)


def extract_end_time_entries(log_file: str) -> List[Tuple[str, int]]:
    """
    Extract end action entries as (timestamp, global_num) pairs in log order.
    """
    try:
        result = subprocess.run(
            ["grep", "-E", "End of action:.*Action -", log_file],
            capture_output=True,
            text=True,
            check=True,
        )

        entries = []
        for line in result.stdout.strip().split("\n"):
            ts_match = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
            if not ts_match:
                continue
            action_match = re.search(r"action: (\d+) ~", line)
            if action_match:
                entries.append((ts_match.group(1), int(action_match.group(1))))

        return entries

    except subprocess.CalledProcessError:
        return []
    except FileNotFoundError:
        print(f"Error: Log file '{log_file}' not found", file=sys.stderr)
        return []


def split_into_runs(
    executed: List[Tuple[str, Dict[str, str]]],
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
        global_num = entry[1]["global_num"]
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
    entries: List[Tuple[str, int]],
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
    h, m, s = map(int, ts.split(":"))
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
    run: List[Tuple[str, Dict[str, str]]],
) -> List[Tuple[str, str, Dict[str, str]]]:
    """
    Group a single run's entries by global_num, tracking first/last start times.

    Each action is logged many times (once per router × log facility). Tracking
    first and last captures the fan-out spread, which is typically a few seconds.

    Returns list of tuples: (start_first, start_last, action_dict)
    """
    seen: Dict[int, List] = {}

    for timestamp, action in run:
        global_num = action["global_num"]

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
    end_times_per_run: List[Dict[int, Tuple[str, str]]] = None,
) -> str:
    """Format executed actions grouped by list and run."""

    if not executed:
        return "No executed actions found."

    runs = split_into_runs(executed)

    output = []
    output.append(f"\n{'=' * 80}")
    output.append(f"Executed Actions Timeline ({len(runs)} run(s))")
    output.append(f"{'=' * 80}\n")

    # Pre-collect check start times (in run/action order) for range-based matching
    all_check_starts = []
    if traffic_blocks:
        for run in runs:
            for start_first, _, action in group_run_entries(run):
                if action["action"] == "check":
                    all_check_starts.append(start_first)

    check_idx = 0

    for run_idx, run in enumerate(runs, 1):
        run_end_times = (
            end_times_per_run[run_idx - 1]
            if end_times_per_run and run_idx - 1 < len(end_times_per_run)
            else {}
        )
        grouped = group_run_entries(run)
        current_list = None

        for start_first, start_last, action in grouped:
            list_num = action["list_num"]
            action_num = action["action_num"]
            total_lists = action["total_lists"]
            global_num = action["global_num"]

            if current_list != list_num:
                if current_list is not None:
                    output.append("")
                output.append(f"List {list_num}/{total_lists} [{run_idx}]")
                output.append("-" * 60)
                current_list = list_num

            action_name = action["action"]
            target = action["target"]
            value = action["value"]

            if action_name == "sleep":
                desc = f"sleep {value}s"
            elif action_name == "check":
                desc = f"CHECK::{value} ✓"
            else:
                target_str = f" [{target}]" if target else ""
                value_str = f" = {value}" if value else ""
                desc = f"{action_name}{target_str}{value_str}"

            start_str = (
                f"{start_first}..{start_last}"
                if start_first != start_last
                else start_first
            )

            end = run_end_times.get(global_num)
            if end:
                end_first, end_last = end
                end_str = (
                    f"{end_first}..{end_last}" if end_first != end_last else end_first
                )
                duration = format_duration(start_first, end_first)
                time_str = f"{start_str} → {end_str} ({duration})"
            else:
                time_str = start_str
            output.append(
                f"  [{time_str}] #{global_num:3d} (Act {action_num:2d}): {desc}"
            )

            if action_name == "check" and traffic_blocks:
                next_ts = (
                    all_check_starts[check_idx + 1]
                    if check_idx + 1 < len(all_check_starts)
                    else None
                )
                blocks = find_traffic_blocks_for_check(
                    start_first, next_ts, traffic_blocks
                )
                for block in blocks:
                    output.append("")
                    output.append(format_traffic_block(block))
                check_idx += 1

        if run_idx < len(runs):
            output.append("")

    return "\n".join(output)


def find_traffic_blocks_for_check(
    check_ts: str,
    next_check_ts: Optional[str],
    traffic_blocks: List[Dict],
) -> List[Dict]:
    """
    Return traffic blocks whose prior_ts falls in [check_ts, next_check_ts).

    Each check action owns the blocks that started after it began and before
    the next check started.  This is reliable because verifyHaStateAndTraffic
    is called from within the check action and checks are spaced minutes apart.
    """
    check_secs = ts_to_seconds(check_ts)
    next_secs = ts_to_seconds(next_check_ts) if next_check_ts else 86400
    return [
        b
        for b in traffic_blocks
        if b["prior_ts"] != "Unknown"
        and check_secs <= ts_to_seconds(b["prior_ts"]) < next_secs
    ]


def _format_ingress_flow_table(pf: Dict, af: Dict) -> List[str]:
    """
    Format a 4-column comparison table for one ingress-flow-stat snapshot pair.
    Rows for identifier fields (flow-name, flow-id, publisher-id) are shown as
    a sub-header; all remaining fields become data rows.
    """
    lines = []
    flow_id = pf.get("flow-id", af.get("flow-id", "?"))
    pub_id = pf.get("publisher-id", af.get("publisher-id", "?"))
    lines.append(f"        ingress-flow-stat  flow-id={flow_id}  pub-id={pub_id}")

    col = 40
    lines.append(f"        {'Stat':<{col}} {'Prior':>10} {'After':>10} {'Delta':>10}")
    lines.append(
        f"        {'-' * col} {'----------':>10} {'----------':>10} {'----------':>10}"
    )

    keys = list(
        dict.fromkeys(
            [k for k in pf if k not in _INGRESS_FLOW_IDENTS]
            + [k for k in af if k not in _INGRESS_FLOW_IDENTS]
        )
    )
    for key in keys:
        p = pf.get(key, "")
        a = af.get(key, "")
        delta = f"{a - p:+d}" if isinstance(p, int) and isinstance(a, int) else ""
        lines.append(f"        {key:<{col}} {str(p):>10} {str(a):>10} {delta:>10}")
    return lines


def _format_egress_flow_table(pf: Dict, af: Dict) -> List[str]:
    """
    Format a 4-column comparison table for one egress-flow-stat snapshot pair.
    Rows for identifier fields (flow-id, flow-state) are shown as a sub-header;
    all remaining fields become data rows.
    """
    lines = []
    flow_id = pf.get("flow-id", af.get("flow-id", "?"))
    flow_state = pf.get("flow-state", af.get("flow-state", "?"))
    lines.append(f"        egress-flow-stat  flow-id={flow_id}  state={flow_state}")

    col = 40
    lines.append(f"        {'Stat':<{col}} {'Prior':>10} {'After':>10} {'Delta':>10}")
    lines.append(
        f"        {'-' * col} {'----------':>10} {'----------':>10} {'----------':>10}"
    )

    keys = list(
        dict.fromkeys(
            [k for k in pf if k not in _EGRESS_FLOW_IDENTS]
            + [k for k in af if k not in _EGRESS_FLOW_IDENTS]
        )
    )
    for key in keys:
        p = pf.get(key, "")
        a = af.get(key, "")
        delta = f"{a - p:+d}" if isinstance(p, int) and isinstance(a, int) else ""
        lines.append(f"        {key:<{col}} {str(p):>10} {str(a):>10} {delta:>10}")
    return lines


def _format_flat_stats_table(label: str, prior: Dict, after: Dict) -> List[str]:
    """Format a 4-column comparison table for a flat broker stat section."""
    lines = [f"        {label}"]
    keys = list(dict.fromkeys(list(prior) + list(after)))
    col = max(40, max((len(k) for k in keys), default=0) + 2)
    lines.append(f"        {'Stat':<{col}} {'Prior':>10} {'After':>10} {'Delta':>10}")
    lines.append(
        f"        {'-' * col} {'----------':>10} {'----------':>10} {'----------':>10}"
    )
    for key in keys:
        p = prior.get(key, "")
        a = after.get(key, "")
        delta = f"{a - p:+d}" if isinstance(p, int) and isinstance(a, int) else ""
        lines.append(f"        {key:<{col}} {str(p):>10} {str(a):>10} {delta:>10}")
    return lines


def _format_client_spool_section(snapshots: Dict) -> List[str]:
    """
    Format all four message-spool-stats sub-sections for one client snapshot pair.

    Sections are rendered in order: ingress flows, egress flows,
    qendpt-bind-stats, publisher-open-stats.
    """
    lines = []
    prior = snapshots.get("prior", {})
    after = snapshots.get("after", {})

    for flows, fmt in (
        ("ingress_flows", _format_ingress_flow_table),
        ("egress_flows", _format_egress_flow_table),
    ):
        pf_list = prior.get(flows, [])
        af_list = after.get(flows, [])
        for i in range(max(len(pf_list), len(af_list))):
            pf = pf_list[i] if i < len(pf_list) else {}
            af = af_list[i] if i < len(af_list) else {}
            lines.extend(fmt(pf, af))

    for label, key in (
        ("qendpt-bind-stats", "qendpt_bind"),
        ("publisher-open-stats", "pub_open"),
    ):
        p = prior.get(key) or {}
        a = after.get(key) or {}
        if p or a:
            lines.extend(_format_flat_stats_table(label, p, a))

    return lines


def _format_side_stats_table(prior: Dict, after: Dict) -> List[str]:
    """
    Format a 4-column comparison table for client-side SDK stats.
    Skips the 'rc' field (always "OK").
    """
    lines = []
    col = 40
    lines.append(f"        {'Stat':<{col}} {'Prior':>12} {'After':>12} {'Delta':>12}")
    lines.append(
        f"        {'-' * col} {'------------':>12} {'------------':>12} {'------------':>12}"
    )
    keys = list(dict.fromkeys(list(prior) + list(after)))
    for key in keys:
        if key == "rc":
            continue
        p = prior.get(key, "")
        a = after.get(key, "")
        if isinstance(p, int) and isinstance(a, int):
            delta = f"{a - p:+d}"
        elif isinstance(p, float) and isinstance(a, float):
            delta = f"{a - p:+.2f}"
        else:
            delta = ""
        lines.append(f"        {key:<{col}} {str(p):>12} {str(a):>12} {delta:>12}")
    return lines


def format_traffic_block(block: Dict) -> str:
    """Format one prior/after stat dump pair as a 4-column comparison table."""
    lines = []
    prior_ts = block.get("prior_ts", "Unknown")
    after_ts = block.get("after_ts", "Unknown")
    lines.append(f"    Traffic dump:  prior={prior_ts}  after={after_ts}")

    pub_clients = block.get("pub_clients", {})
    sub_clients = block.get("sub_clients", {})

    if pub_clients:
        lines.append("      Publisher client message-spool-stats:")
        for name in sorted(pub_clients):
            short = name.replace("c_vmrRedundancyRandomActions_pub_", "pub_")
            lines.append(f"\n      Client: {short}")
            lines.extend(_format_client_spool_section(pub_clients[name]))
    else:
        lines.append("      (no publisher client stats captured)")

    if sub_clients:
        lines.append("\n      Subscriber client message-spool-stats:")
        for name in sorted(sub_clients):
            short = name.replace("c_vmrRedundancyRandomActions_sub_", "sub_")
            lines.append(f"\n      Client: {short}")
            lines.extend(_format_client_spool_section(sub_clients[name]))

    global_spools = block.get("global_spools", {})
    if global_spools:
        lines.append("\n      Global message-spool stats:")
        for router in sorted(global_spools):
            lines.append(f"\n      Router: {router}")
            snaps = global_spools[router]
            p = snaps.get("prior", {})
            a = snaps.get("after", {})
            if p or a:
                lines.extend(_format_flat_stats_table("message-spool-stats", p, a))

    vpn_spools = block.get("vpn_spools", {})
    if vpn_spools:
        lines.append("\n      VPN message-spool stats:")
        for key in sorted(vpn_spools):
            router, vpn = key.split(":", 1)
            lines.append(f"\n      Router: {router}  VPN: {vpn}")
            snaps = vpn_spools[key]
            p = snaps.get("prior", {})
            a = snaps.get("after", {})
            if p or a:
                lines.extend(_format_flat_stats_table("message-spool-stats", p, a))

    queues = block.get("queues", {})
    if queues:
        lines.append("\n      Queue stats:")
        for key in sorted(queues):
            router, qname = key.split(":", 1)
            lines.append(f"\n      Router: {router}  Queue: {qname}")
            snaps = queues[key]
            p = snaps.get("prior", {})
            a = snaps.get("after", {})
            if p or a:
                lines.extend(_format_flat_stats_table("queue-info", p, a))

    pub_side = block.get("pub_side", {})
    if pub_side.get("prior") and pub_side.get("after"):
        lines.append("\n      Publisher client-side stats:")
        lines.extend(_format_side_stats_table(pub_side["prior"], pub_side["after"]))

    sub_side = block.get("sub_side", {})
    if sub_side.get("prior") and sub_side.get("after"):
        lines.append("\n      Subscriber client-side stats:")
        lines.extend(_format_side_stats_table(sub_side["prior"], sub_side["after"]))

    return "\n".join(lines)


def main():
    # Parse command line arguments
    log_file = "/tmp/debug/log.txt"
    show_executed = False
    show_traffic = False
    filter_list = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ("--help", "-h"):
            print_help()
        elif arg == "--executed":
            show_executed = True
        elif arg == "--traffic":
            show_traffic = True
        elif arg == "--list" and i + 1 < len(sys.argv):
            filter_list = int(sys.argv[i + 1])
            i += 1
        elif not arg.startswith("--"):
            log_file = arg
        i += 1

    print(f"Parsing actions from: {log_file}")
    if show_executed:
        mode_str = "Executed actions"
        if filter_list is not None:
            mode_str += f" (List {filter_list} only)"
        if show_traffic:
            mode_str += " with traffic stats"
    elif show_traffic:
        mode_str = "Traffic dump pairs"
    else:
        mode_str = "Declared action lists"
        if filter_list is not None:
            mode_str += f" (List {filter_list} only)"
    print(f"Mode: {mode_str}\n")

    if show_executed:
        executed = extract_executed_actions(log_file)

        if not executed:
            print("No executed actions found in log file.")
            return 1

        if filter_list is not None:
            executed = [
                (ts, act) for ts, act in executed if act["list_num"] == filter_list
            ]

        print(f"Found {len(executed)} executed action(s)\n")

        traffic_blocks = None
        if show_traffic:
            traffic_blocks = extract_traffic_blocks(log_file)
            if traffic_blocks:
                print(f"Found {len(traffic_blocks)} traffic dump pair(s)\n")

        end_times_per_run = split_end_times_into_runs(
            extract_end_time_entries(log_file)
        )
        print(format_executed_actions(executed, traffic_blocks, end_times_per_run))

    elif show_traffic:
        traffic_blocks = extract_traffic_blocks(log_file)
        if not traffic_blocks:
            print("No traffic dump pairs found in log file.")
            return 1
        print(f"Found {len(traffic_blocks)} traffic dump pair(s)\n")
        for idx, block in enumerate(traffic_blocks, 1):
            print(f"\n{'=' * 70}")
            print(f"Dump pair {idx}/{len(traffic_blocks)}")
            print("=" * 70)
            print(format_traffic_block(block))

    else:
        action_lists = extract_action_lists(log_file)

        if not action_lists:
            print("No action lists found in log file.")
            return 1

        print(f"Found {len(action_lists)} action list(s)\n")

        for timestamp, full_line, action_text in action_lists:
            actions = parse_actions(action_text)
            print(format_action_list_compact(timestamp, actions))

    return 0


if __name__ == "__main__":
    sys.exit(main())
