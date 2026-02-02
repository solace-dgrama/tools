#!/usr/bin/env python3
"""
Sort PRs from results.json by review time (time_to_merge_hours).
"""

import json
import sys
from pathlib import Path


def sort_prs_by_review_time(input_file, output_file=None, descending=True):
    """
    Sort pull requests by review time.

    Args:
        input_file: Path to the input JSON file
        output_file: Path to the output JSON file (optional, defaults to stdout)
        descending: Sort in descending order (longest review time first) if True
    """
    # Read the input file
    with open(input_file, 'r') as f:
        data = json.load(f)

    # Get the pull requests
    pull_requests = data.get('pull_requests', [])

    # Sort by time_to_merge_hours
    # Handle None values by treating them as negative infinity (they'll go to the end)
    sorted_prs = sorted(
        pull_requests,
        key=lambda pr: pr.get('time_to_merge_hours') if pr.get('time_to_merge_hours') is not None else float('-inf'),
        reverse=descending
    )

    # Update the data with sorted PRs
    data['pull_requests'] = sorted_prs

    # Output the results
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Sorted {len(sorted_prs)} PRs by review time. Output written to {output_file}")
    else:
        # Print to stdout
        json.dump(data, sys.stdout, indent=2)
        print(file=sys.stderr)  # Add newline to stderr
        print(f"Sorted {len(sorted_prs)} PRs by review time.", file=sys.stderr)

    # Print summary statistics
    merged_prs = [pr for pr in sorted_prs if pr.get('time_to_merge_hours') is not None]
    if merged_prs:
        times = [pr['time_to_merge_hours'] for pr in merged_prs]
        print(f"\nReview Time Statistics:", file=sys.stderr)
        print(f"  Total merged PRs: {len(merged_prs)}", file=sys.stderr)
        print(f"  Longest review time: {max(times):.2f} hours (PR #{merged_prs[0]['number']})", file=sys.stderr)
        print(f"  Shortest review time: {min(times):.2f} hours", file=sys.stderr)
        print(f"  Average review time: {sum(times)/len(times):.2f} hours", file=sys.stderr)


def main():
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Sort pull requests by review time (time_to_merge_hours)'
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        default='results.json',
        help='Input JSON file (default: results.json)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output JSON file (default: stdout)'
    )
    parser.add_argument(
        '-a', '--ascending',
        action='store_true',
        help='Sort in ascending order (shortest review time first)'
    )

    args = parser.parse_args()

    # Check if input file exists
    if not Path(args.input_file).exists():
        print(f"Error: Input file '{args.input_file}' not found", file=sys.stderr)
        sys.exit(1)

    # Sort the PRs
    sort_prs_by_review_time(
        args.input_file,
        args.output,
        descending=not args.ascending
    )


if __name__ == '__main__':
    main()
