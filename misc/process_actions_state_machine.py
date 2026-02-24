#!/usr/bin/env python3
"""
Script to extract actions and timestamps from VMR HA state machine test logs.

This script parses the log.txt file from vmrhastatemachine_tr test runs and
extracts all numbered actions with their start and end timestamps.

Usage:
    python process_actions_state_machine.py <log_file_path>

Example:
    python process_actions_state_machine.py /home/public/RND/AFW/loadTestResults/10.25.0.189/vmrhastatemachine_tr_CCSMP/logs/log.txt
"""

import re
import sys
from datetime import datetime
from typing import List, Tuple, Optional


class Action:
    """Represents a single test action with start and optional end timestamp."""

    def __init__(self, number: int, description: str, start_time: str, start_date: str):
        self.number = number
        self.description = description
        self.start_time = start_time
        self.start_date = start_date
        self.end_time: Optional[str] = None
        self.end_date: Optional[str] = None

    def set_end_time(self, end_time: str, end_date: str):
        """Set the end timestamp for this action."""
        self.end_time = end_time
        self.end_date = end_date

    def duration_seconds(self) -> Optional[float]:
        """Calculate duration in seconds if both start and end times are set."""
        if not self.end_time or not self.start_time:
            return None

        try:
            # Combine date and time for parsing
            start_datetime = datetime.strptime(
                f"{self.start_date} {self.start_time}",
                "%a, %d %b %Y %H:%M:%S"
            )
            end_datetime = datetime.strptime(
                f"{self.end_date} {self.end_time}",
                "%a, %d %b %Y %H:%M:%S"
            )
            delta = end_datetime - start_datetime
            return delta.total_seconds()
        except ValueError:
            return None

    def __str__(self) -> str:
        duration = self.duration_seconds()
        duration_str = f"{duration:.1f}s" if duration is not None else "N/A"

        if self.end_time:
            return (f"[{self.number:3d}] {self.start_time} -> {self.end_time} "
                   f"({duration_str:>8s}) | {self.description}")
        else:
            return f"[{self.number:3d}] {self.start_time} (no end)          | {self.description}"


def extract_actions(log_file_path: str) -> List[Action]:
    """
    Extract all numbered actions from the log file.

    Args:
        log_file_path: Path to the log.txt file

    Returns:
        List of Action objects sorted by action number
    """
    # Pattern to match ActionStart lines with numbered actions
    # Example: [14:37:33] [11] [notice] [RESULT] [::L1::Test::ActionStart] { Method params: 1 ~ Prepare for action...
    action_start_pattern = re.compile(
        r'^\[(\d{2}:\d{2}:\d{2})\].*\[::L1::Test::ActionStart\].*Method params: (\d+) ~ (.*)$'
    )

    # Pattern to match ActionEnd
    action_end_pattern = re.compile(
        r'^\[(\d{2}:\d{2}:\d{2})\].*\[::L1::Test::ActionEnd\]'
    )

    # Pattern to extract date from log lines (appears at various points)
    # Example: Fri, 20 Feb 2026 15:58:36 -0500
    date_pattern = re.compile(
        r'([A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4}) (\d{2}:\d{2}:\d{2})'
    )

    actions = []
    current_date = None
    pending_action_start = None

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Try to extract date if present in this line
                date_match = date_pattern.search(line)
                if date_match:
                    current_date = date_match.group(1)

                # Check for ActionStart
                start_match = action_start_pattern.search(line)
                if start_match:
                    start_time = start_match.group(1)
                    action_num = int(start_match.group(2))
                    description = start_match.group(3).strip()

                    # Close previous action if it exists
                    if pending_action_start:
                        actions.append(pending_action_start)

                    # Create new action
                    pending_action_start = Action(
                        action_num,
                        description,
                        start_time,
                        current_date or "Unknown"
                    )
                    continue

                # Check for ActionEnd
                end_match = action_end_pattern.search(line)
                if end_match and pending_action_start:
                    end_time = end_match.group(1)
                    pending_action_start.set_end_time(end_time, current_date or "Unknown")
                    actions.append(pending_action_start)
                    pending_action_start = None
                    continue

            # Add last pending action if exists
            if pending_action_start:
                actions.append(pending_action_start)

    except FileNotFoundError:
        print(f"Error: File not found: {log_file_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    # Sort by action number
    actions.sort(key=lambda a: a.number)

    return actions


def print_actions(actions: List[Action]):
    """Print actions in a formatted table."""
    if not actions:
        print("No actions found in log file.")
        return

    print("\n" + "=" * 120)
    print(f"{'Action':<6} {'Start Time':<10} {'End Time':<10} {'Duration':<10} | Description")
    print("=" * 120)

    for action in actions:
        duration = action.duration_seconds()
        duration_str = f"{duration:.1f}s" if duration is not None else "N/A"
        end_str = action.end_time if action.end_time else "N/A"

        print(f"{action.number:<6d} {action.start_time:<10} {end_str:<10} {duration_str:<10} | {action.description}")

    print("=" * 120)
    print(f"Total actions: {len(actions)}")

    # Calculate total duration
    completed = [a for a in actions if a.duration_seconds() is not None]
    if completed:
        total_duration = sum(a.duration_seconds() for a in completed)
        print(f"Total duration of completed actions: {total_duration:.1f}s ({total_duration/60:.1f}min)")


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python process_actions_state_machine.py <log_file_path>")
        print("\nExample:")
        print("  python process_actions_state_machine.py /home/public/RND/AFW/loadTestResults/10.25.0.189/vmrhastatemachine_tr_CCSMP/logs/log.txt")
        sys.exit(1)

    log_file_path = sys.argv[1]

    print(f"Processing log file: {log_file_path}")

    actions = extract_actions(log_file_path)
    print_actions(actions)


if __name__ == "__main__":
    main()
