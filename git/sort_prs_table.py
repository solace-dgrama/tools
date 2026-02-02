#!/usr/bin/env python3
"""
Sort PRs from results.json by review time and display in table format.
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def format_hours(hours):
    """Format hours into a human-readable string."""
    if hours is None:
        return "N/A"

    if hours < 1:
        return f"{hours*60:.1f}m"
    elif hours < 24:
        return f"{hours:.1f}h"
    else:
        days = hours / 24
        return f"{days:.1f}d"


def format_date(date_str):
    """Format ISO date string to shorter format."""
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except:
        return date_str[:10]


def truncate(text, length=50):
    """Truncate text to specified length."""
    if len(text) <= length:
        return text
    return text[:length-3] + "..."


def print_table(prs, format_type='text', sort_by='review_time', ascending=False, show_closed=False):
    """
    Print PRs in table format.

    Args:
        prs: List of pull requests
        format_type: 'text', 'csv', or 'markdown'
        sort_by: Field to sort by
        ascending: Sort order
        show_closed: Include closed (unmerged) PRs
    """
    # Filter PRs based on show_closed flag
    if not show_closed:
        filtered_prs = [pr for pr in prs if pr.get('state') == 'MERGED']
    else:
        filtered_prs = prs

    # Sort PRs
    sort_keys = {
        'review_time': lambda pr: pr.get('time_to_merge_hours') if pr.get('time_to_merge_hours') is not None else float('-inf'),
        'first_response': lambda pr: pr.get('time_to_first_response_hours') if pr.get('time_to_first_response_hours') is not None else float('inf'),
        'first_comment': lambda pr: pr.get('time_to_first_comment_hours') if pr.get('time_to_first_comment_hours') is not None else float('inf'),
        'first_review': lambda pr: pr.get('time_to_first_review_hours') if pr.get('time_to_first_review_hours') is not None else float('inf'),
        'first_approval': lambda pr: pr.get('time_to_first_approval_hours') if pr.get('time_to_first_approval_hours') is not None else float('inf'),
        'number': lambda pr: pr.get('number', 0),
        'created': lambda pr: pr.get('created_at', ''),
        'size': lambda pr: pr.get('total_lines_changed', 0),
        'reviews': lambda pr: pr.get('review_count', 0),
    }

    sorted_prs = sorted(filtered_prs, key=sort_keys.get(sort_by, sort_keys['review_time']), reverse=not ascending)

    if format_type == 'csv':
        print_csv(sorted_prs)
    elif format_type == 'markdown':
        print_markdown(sorted_prs)
    else:
        print_text_table(sorted_prs)


def print_csv(prs):
    """Print PRs in CSV format."""
    import csv
    import sys

    writer = csv.writer(sys.stdout)

    # Header
    writer.writerow([
        'PR#', 'Title', 'Author', 'State', 'First Response (hrs)', 'First Comment (hrs)',
        'First Review (hrs)', 'First Approval (hrs)', 'Total Time (hrs)',
        'Created', 'Merged', 'Lines Changed', 'Reviews', 'Approvals', 'URL'
    ])

    # Data rows
    for pr in prs:
        writer.writerow([
            pr.get('number', ''),
            pr.get('title', ''),
            pr.get('author', ''),
            pr.get('state', ''),
            pr.get('time_to_first_response_hours', ''),
            pr.get('time_to_first_comment_hours', ''),
            pr.get('time_to_first_review_hours', ''),
            pr.get('time_to_first_approval_hours', ''),
            pr.get('time_to_merge_hours', ''),
            format_date(pr.get('created_at')),
            format_date(pr.get('merged_at')),
            pr.get('total_lines_changed', ''),
            pr.get('review_count', ''),
            pr.get('approvals', ''),
            pr.get('url', '')
        ])


def print_markdown(prs):
    """Print PRs in Markdown table format."""
    # Header
    print("| PR# | Title | Author | First Resp | First Rev | First App | Total Time | Lines | Reviews |")
    print("|-----|-------|--------|------------|-----------|-----------|------------|-------|---------|")

    # Data rows
    for pr in prs:
        print(f"| [{pr.get('number', '')}]({pr.get('url', '')}) "
              f"| {truncate(pr.get('title', ''), 35)} "
              f"| {pr.get('author', '')} "
              f"| {format_hours(pr.get('time_to_first_response_hours'))} "
              f"| {format_hours(pr.get('time_to_first_review_hours'))} "
              f"| {format_hours(pr.get('time_to_first_approval_hours'))} "
              f"| {format_hours(pr.get('time_to_merge_hours'))} "
              f"| {pr.get('total_lines_changed', 'N/A')} "
              f"| {pr.get('review_count', 'N/A')} |")


def print_text_table(prs):
    """Print PRs in plain text table format."""
    # Column widths
    widths = {
        'number': 6,
        'title': 45,
        'author': 18,
        'first_resp': 11,
        'first_rev': 10,
        'first_app': 10,
        'total': 11,
        'lines': 8,
        'reviews': 8
    }

    # Header
    header = (
        f"{'PR#':<{widths['number']}} "
        f"{'Title':<{widths['title']}} "
        f"{'Author':<{widths['author']}} "
        f"{'First Resp':<{widths['first_resp']}} "
        f"{'First Rev':<{widths['first_rev']}} "
        f"{'First App':<{widths['first_app']}} "
        f"{'Total Time':<{widths['total']}} "
        f"{'Lines':<{widths['lines']}} "
        f"{'Reviews':<{widths['reviews']}}"
    )

    print(header)
    print("-" * len(header))

    # Data rows
    for pr in prs:
        row = (
            f"{pr.get('number', 'N/A'):<{widths['number']}} "
            f"{truncate(pr.get('title', ''), widths['title']):<{widths['title']}} "
            f"{truncate(pr.get('author', ''), widths['author']):<{widths['author']}} "
            f"{format_hours(pr.get('time_to_first_response_hours')):<{widths['first_resp']}} "
            f"{format_hours(pr.get('time_to_first_review_hours')):<{widths['first_rev']}} "
            f"{format_hours(pr.get('time_to_first_approval_hours')):<{widths['first_app']}} "
            f"{format_hours(pr.get('time_to_merge_hours')):<{widths['total']}} "
            f"{pr.get('total_lines_changed', 'N/A'):<{widths['lines']}} "
            f"{pr.get('review_count', 'N/A'):<{widths['reviews']}}"
        )
        print(row)

    # Summary statistics
    merged_prs = [pr for pr in prs if pr.get('time_to_merge_hours') is not None]
    prs_with_response = [pr for pr in prs if pr.get('time_to_first_response_hours') is not None]

    print("\n" + "=" * len(header))
    print(f"Total PRs: {len(prs)} (Merged: {len(merged_prs)})")

    if merged_prs:
        times = [pr['time_to_merge_hours'] for pr in merged_prs]
        print(f"\nTotal Time to Merge:")
        print(f"  Longest: {format_hours(max(times))} ({max(times):.2f} hours)")
        print(f"  Shortest: {format_hours(min(times))} ({min(times):.2f} hours)")
        print(f"  Average: {format_hours(sum(times)/len(times))} ({sum(times)/len(times):.2f} hours)")

    if prs_with_response:
        response_times = [pr['time_to_first_response_hours'] for pr in prs_with_response]
        print(f"\nTime to First Response:")
        print(f"  Fastest: {format_hours(min(response_times))} ({min(response_times):.2f} hours)")
        print(f"  Slowest: {format_hours(max(response_times))} ({max(response_times):.2f} hours)")
        print(f"  Average: {format_hours(sum(response_times)/len(response_times))} ({sum(response_times)/len(response_times):.2f} hours)")


def main():
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Sort and display pull requests in table format'
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        default='results.json',
        help='Input JSON file (default: results.json)'
    )
    parser.add_argument(
        '-f', '--format',
        choices=['text', 'csv', 'markdown'],
        default='text',
        help='Output format (default: text)'
    )
    parser.add_argument(
        '-s', '--sort',
        choices=['review_time', 'first_response', 'first_comment', 'first_review', 'first_approval', 'number', 'created', 'size', 'reviews'],
        default='review_time',
        help='Sort by field (default: review_time)'
    )
    parser.add_argument(
        '-a', '--ascending',
        action='store_true',
        help='Sort in ascending order'
    )
    parser.add_argument(
        '-c', '--show-closed',
        action='store_true',
        help='Include closed (unmerged) PRs'
    )
    parser.add_argument(
        '-n', '--limit',
        type=int,
        help='Limit number of results'
    )

    args = parser.parse_args()

    # Check if input file exists
    if not Path(args.input_file).exists():
        print(f"Error: Input file '{args.input_file}' not found", file=sys.stderr)
        sys.exit(1)

    # Read the input file
    with open(args.input_file, 'r') as f:
        data = json.load(f)

    # Get the pull requests
    prs = data.get('pull_requests', [])

    # Limit results if specified
    if args.limit:
        prs = prs[:args.limit]

    # Print the table
    print_table(prs, args.format, args.sort, args.ascending, args.show_closed)


if __name__ == '__main__':
    main()
