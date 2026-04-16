#!/usr/bin/env python3
"""Convert a GELF CSV log file (as exported by some log collectors) to
syslog debug-log format, writing to stdout.

Usage: gelf_csv_to_syslog.py <csv_file>

CSV format expected:
    timestamp,source,message
where `message` is either a GELF JSON object (or multiple concatenated
objects) or an already-formatted syslog line.

Output format:
    <timestamp> <facility.level> <host> appuser: <short_message>
"""

import csv
import json
import re
import signal
import sys
from datetime import datetime, timezone

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

LEVEL_NAMES = {
    "0": "emerg",
    "1": "alert",
    "2": "crit",
    "3": "err",
    "4": "warning",
    "5": "notice",
    "6": "info",
    "7": "debug",
}

LOCAL_TZ = datetime.now(timezone.utc).astimezone().tzinfo

TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2}))\s"
)


def to_local(ts_str):
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    tz = dt.strftime("%z")  # +HHMM
    return ts + tz[:-2] + ":" + tz[-2:]  # -> +HH:MM


def parse_json_objects(s):
    """Yield all JSON objects from a string that may contain multiple."""
    decoder = json.JSONDecoder()
    s = s.lstrip()
    while s:
        obj, end = decoder.raw_decode(s)
        yield obj
        s = s[end:].lstrip()


def convert(csv_file):
    with open(csv_file) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            try:
                ts_col, source, message = row
            except ValueError:
                print(f"Warning: skipping malformed row: {row!r}", file=sys.stderr)
                continue
            if message.startswith("{"):
                try:
                    for msg in parse_json_objects(message):
                        ts = to_local(ts_col)
                        facility = msg.get("_facility", "local0")
                        level = LEVEL_NAMES.get(msg.get("level", "6"), "info")
                        host = msg.get("host", source)
                        short_msg = msg.get("short_message", "")
                        print(f"{ts} <{facility}.{level}> {host} appuser: {short_msg}")
                except json.JSONDecodeError as e:
                    print(f"Warning: skipping bad JSON in row: {e}", file=sys.stderr)
            else:
                m = TS_RE.match(message)
                if m:
                    ts = to_local(m.group(1))
                    print(ts + " " + message[m.end() :])
                else:
                    print(message)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <csv_file>", file=sys.stderr)
        sys.exit(1)
    try:
        convert(sys.argv[1])
    except BrokenPipeError:
        sys.exit(0)
