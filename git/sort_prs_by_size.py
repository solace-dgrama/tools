#!/usr/bin/env python3
"""
Sort and analyze PRs from results.json by various size metrics.
"""

import json
import argparse
from typing import List, Dict, Any
from datetime import datetime


def load_pr_data(filename: str = 'results.json') -> Dict[str, Any]:
    """Load PR data from JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)


def format_number(num: int) -> str:
    """Format number with comma separators."""
    return f"{num:,}"


def format_time(hours: float) -> str:
    """Format time in hours to a more readable format."""
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{hours*60:.0f}m"
    elif hours < 24:
        return f"{hours:.1f}h"
    else:
        days = hours / 24
        return f"{days:.1f}d"


def print_pr_summary(prs: List[Dict[str, Any]], sort_by: str, limit: int = None):
    """Print a formatted summary of PRs."""

    # Determine column header based on sort metric
    metric_headers = {
        'total_lines_changed': 'Lines',
        'additions': 'Additions',
        'deletions': 'Deletions',
        'changed_files': 'Files',
        'commits': 'Commits',
        'time_to_merge_hours': 'Time',
        'review_count': 'Reviews',
        'comment_count': 'Comments'
    }

    metric_header = metric_headers.get(sort_by, 'Metric')

    # Print header
    print(f"\n{'Rank':<6} {'PR #':<8} {metric_header:<12} {'Files':<8} {'State':<10} {'Author':<20} {'Title'}")
    print("=" * 150)

    # Print each PR
    prs_to_show = prs[:limit] if limit else prs

    for i, pr in enumerate(prs_to_show, 1):
        pr_num = pr['number']
        metric_val = pr[sort_by]

        # Format metric value based on type
        if sort_by == 'time_to_merge_hours':
            metric_display = format_time(metric_val)
        else:
            metric_display = format_number(metric_val) if metric_val is not None else "N/A"

        files = pr['changed_files']
        state = pr['state']
        author = pr['author'][:18]  # Truncate if too long
        title = pr['title'][:80]  # Truncate title

        print(f"{i:<6} {pr_num:<8} {metric_display:<12} {files:<8} {state:<10} {author:<20} {title}")


def print_statistics(prs: List[Dict[str, Any]], data: Dict[str, Any]):
    """Print overall statistics."""
    total_prs = len(prs)
    merged_prs = len([pr for pr in prs if pr['state'] == 'MERGED'])
    closed_prs = len([pr for pr in prs if pr['state'] == 'CLOSED'])

    total_lines = sum(pr['total_lines_changed'] for pr in prs)
    total_additions = sum(pr['additions'] for pr in prs)
    total_deletions = sum(pr['deletions'] for pr in prs)
    total_files = sum(pr['changed_files'] for pr in prs)

    avg_lines = total_lines / total_prs if total_prs > 0 else 0
    avg_files = total_files / total_prs if total_prs > 0 else 0

    print("\n" + "=" * 80)
    print(f"STATISTICS for {data['team']}")
    print(f"Period: {data['start_date']} to {data['end_date']}")
    print(f"Repositories: {', '.join(data['repositories'])}")
    print("=" * 80)
    print(f"Total PRs:        {format_number(total_prs)} ({merged_prs} merged, {closed_prs} closed)")
    print(f"Total Lines:      {format_number(total_lines)} (+{format_number(total_additions)} / -{format_number(total_deletions)})")
    print(f"Total Files:      {format_number(total_files)}")
    print(f"Avg Lines/PR:     {format_number(int(avg_lines))}")
    print(f"Avg Files/PR:     {avg_files:.1f}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Sort and analyze PRs by size',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Sort by total lines changed (default)
  %(prog)s --sort additions -n 20   # Show top 20 by additions
  %(prog)s --sort changed_files     # Sort by number of files changed
  %(prog)s --sort time_to_merge_hours --reverse  # Longest merge times first
        """
    )

    parser.add_argument(
        '-f', '--file',
        default='results.json',
        help='Input JSON file (default: results.json)'
    )

    parser.add_argument(
        '-s', '--sort',
        default='total_lines_changed',
        choices=[
            'total_lines_changed',
            'additions',
            'deletions',
            'changed_files',
            'commits',
            'time_to_merge_hours',
            'review_count',
            'comment_count'
        ],
        help='Metric to sort by (default: total_lines_changed)'
    )

    parser.add_argument(
        '-n', '--limit',
        type=int,
        default=None,
        help='Limit number of PRs to display (default: all)'
    )

    parser.add_argument(
        '-r', '--reverse',
        action='store_true',
        help='Reverse sort order (smallest first instead of largest)'
    )

    parser.add_argument(
        '--no-stats',
        action='store_true',
        help='Skip printing statistics'
    )

    parser.add_argument(
        '--merged-only',
        action='store_true',
        help='Show only merged PRs'
    )

    parser.add_argument(
        '--author',
        help='Filter by author name'
    )

    args = parser.parse_args()

    # Load data
    try:
        data = load_pr_data(args.file)
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found")
        return 1
    except json.JSONDecodeError:
        print(f"Error: File '{args.file}' is not valid JSON")
        return 1

    prs = data['pull_requests']

    # Apply filters
    if args.merged_only:
        prs = [pr for pr in prs if pr['state'] == 'MERGED']

    if args.author:
        prs = [pr for pr in prs if args.author.lower() in pr['author'].lower()]

    # Sort PRs
    # Handle None values for metrics that might be null (like time_to_merge_hours for non-merged PRs)
    sorted_prs = sorted(
        prs,
        key=lambda x: x[args.sort] if x[args.sort] is not None else -1,
        reverse=not args.reverse
    )

    # Print statistics
    if not args.no_stats:
        print_statistics(prs, data)

    # Print sorted PRs
    print_pr_summary(sorted_prs, args.sort, args.limit)

    # Print summary at bottom
    displayed = args.limit if args.limit and args.limit < len(sorted_prs) else len(sorted_prs)
    print(f"\nShowing {displayed} of {len(sorted_prs)} PRs (sorted by {args.sort}, {'ascending' if args.reverse else 'descending'})")

    return 0


if __name__ == '__main__':
    exit(main())
