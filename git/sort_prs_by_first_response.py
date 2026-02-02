#!/usr/bin/env python3
"""
Sort PRs by time to first response (review, comment, or approval).
Uses data from the JSON file (no GitHub API calls).
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def get_pr_review_timeline(repo, pr_number):
    """
    Get the timeline of reviews and comments for a PR using gh CLI.

    Returns dict with:
        - first_comment_hours: Time to first comment
        - first_review_hours: Time to first review
        - first_approval_hours: Time to first approval
    """
    try:
        # Get PR details including timeline
        cmd = f'gh api repos/{repo}/pulls/{pr_number}/reviews'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return None

        reviews = json.loads(result.stdout)

        # Get comments timeline
        cmd = f'gh api repos/{repo}/issues/{pr_number}/comments'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

        comments = []
        if result.returncode == 0:
            comments = json.loads(result.stdout)

        return {
            'reviews': reviews,
            'comments': comments
        }
    except Exception as e:
        print(f"Error fetching timeline for PR {pr_number}: {e}", file=sys.stderr)
        return None


def calculate_time_to_first_response(pr, timeline_data=None):
    """
    Calculate time to first response (comment, review, or approval).

    Returns dict with timing information.
    """
    created_at = pr.get('created_at')
    if not created_at:
        return None

    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))

    result = {
        'first_comment_hours': None,
        'first_review_hours': None,
        'first_approval_hours': None,
        'first_response_hours': None
    }

    if not timeline_data:
        return result

    earliest_times = []

    # Process reviews
    if timeline_data.get('reviews'):
        for review in timeline_data['reviews']:
            submitted_at = review.get('submitted_at')
            if submitted_at:
                review_dt = datetime.fromisoformat(submitted_at.replace('Z', '+00:00'))
                hours = (review_dt - created_dt).total_seconds() / 3600

                if result['first_review_hours'] is None or hours < result['first_review_hours']:
                    result['first_review_hours'] = hours

                if review.get('state') == 'APPROVED':
                    if result['first_approval_hours'] is None or hours < result['first_approval_hours']:
                        result['first_approval_hours'] = hours

                earliest_times.append(hours)

    # Process comments
    if timeline_data.get('comments'):
        for comment in timeline_data['comments']:
            created_at_comment = comment.get('created_at')
            if created_at_comment:
                comment_dt = datetime.fromisoformat(created_at_comment.replace('Z', '+00:00'))
                hours = (comment_dt - created_dt).total_seconds() / 3600

                if result['first_comment_hours'] is None or hours < result['first_comment_hours']:
                    result['first_comment_hours'] = hours

                earliest_times.append(hours)

    # Calculate first response (earliest of any activity)
    if earliest_times:
        result['first_response_hours'] = min(earliest_times)

    return result


def enrich_prs_with_response_times(prs):
    """
    Enrich PRs with response time data from the JSON file itself.
    The data is already present in results.json, so no GitHub API calls are needed.
    """
    enriched_prs = []

    for pr in prs:
        # Extract timing data that's already in the JSON
        response_times = {
            'first_comment_hours': pr.get('time_to_first_comment_hours'),
            'first_review_hours': pr.get('time_to_first_review_hours'),
            'first_approval_hours': pr.get('time_to_first_approval_hours'),
            'first_response_hours': pr.get('time_to_first_response_hours')
        }

        pr['response_times'] = response_times
        enriched_prs.append(pr)

    return enriched_prs


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
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length-3] + "..."


def print_table(prs, sort_by='first_response', ascending=False, format_type='text', limit=None):
    """Print PRs in table format sorted by response time."""

    # Sort PRs
    sort_keys = {
        'first_response': lambda pr: pr.get('response_times', {}).get('first_response_hours') if pr.get('response_times', {}).get('first_response_hours') is not None else float('inf'),
        'first_review': lambda pr: pr.get('response_times', {}).get('first_review_hours') if pr.get('response_times', {}).get('first_review_hours') is not None else float('inf'),
        'first_comment': lambda pr: pr.get('response_times', {}).get('first_comment_hours') if pr.get('response_times', {}).get('first_comment_hours') is not None else float('inf'),
        'first_approval': lambda pr: pr.get('response_times', {}).get('first_approval_hours') if pr.get('response_times', {}).get('first_approval_hours') is not None else float('inf'),
        'total_time': lambda pr: pr.get('time_to_merge_hours') if pr.get('time_to_merge_hours') is not None else float('inf'),
    }

    sorted_prs = sorted(prs, key=sort_keys.get(sort_by, sort_keys['first_response']), reverse=not ascending)

    if limit:
        sorted_prs = sorted_prs[:limit]

    if format_type == 'csv':
        print_csv(sorted_prs)
    elif format_type == 'markdown':
        print_markdown(sorted_prs)
    else:
        print_text_table(sorted_prs)


def print_csv(prs):
    """Print PRs in CSV format."""
    import csv

    writer = csv.writer(sys.stdout)

    writer.writerow([
        'PR#', 'Title', 'Author', 'State', 'First Response', 'First Comment',
        'First Review', 'First Approval', 'Total Time', 'Created', 'Lines', 'Reviews', 'Approvals'
    ])

    for pr in prs:
        rt = pr.get('response_times', {})
        writer.writerow([
            pr.get('number', ''),
            pr.get('title', ''),
            pr.get('author', ''),
            pr.get('state', ''),
            rt.get('first_response_hours', ''),
            rt.get('first_comment_hours', ''),
            rt.get('first_review_hours', ''),
            rt.get('first_approval_hours', ''),
            pr.get('time_to_merge_hours', ''),
            format_date(pr.get('created_at')),
            pr.get('total_lines_changed', ''),
            pr.get('review_count', ''),
            pr.get('approvals', '')
        ])


def print_markdown(prs):
    """Print PRs in Markdown table format."""
    print("| PR# | Title | Author | First Response | First Review | First Approval | Total Time | Lines |")
    print("|-----|-------|--------|----------------|--------------|----------------|------------|-------|")

    for pr in prs:
        rt = pr.get('response_times', {})
        print(f"| [{pr.get('number', '')}]({pr.get('url', '')}) "
              f"| {truncate(pr.get('title', ''), 35)} "
              f"| {pr.get('author', '')} "
              f"| {format_hours(rt.get('first_response_hours'))} "
              f"| {format_hours(rt.get('first_review_hours'))} "
              f"| {format_hours(rt.get('first_approval_hours'))} "
              f"| {format_hours(pr.get('time_to_merge_hours'))} "
              f"| {pr.get('total_lines_changed', 'N/A')} |")


def print_text_table(prs):
    """Print PRs in plain text table format."""
    widths = {
        'number': 6,
        'title': 45,
        'author': 18,
        'first_resp': 13,
        'first_rev': 12,
        'first_app': 13,
        'total': 11,
        'lines': 8
    }

    header = (
        f"{'PR#':<{widths['number']}} "
        f"{'Title':<{widths['title']}} "
        f"{'Author':<{widths['author']}} "
        f"{'First Resp':<{widths['first_resp']}} "
        f"{'First Rev':<{widths['first_rev']}} "
        f"{'First App':<{widths['first_app']}} "
        f"{'Total Time':<{widths['total']}} "
        f"{'Lines':<{widths['lines']}}"
    )

    print(header)
    print("-" * len(header))

    for pr in prs:
        rt = pr.get('response_times', {})
        row = (
            f"{pr.get('number', 'N/A'):<{widths['number']}} "
            f"{truncate(pr.get('title', ''), widths['title']):<{widths['title']}} "
            f"{truncate(pr.get('author', ''), widths['author']):<{widths['author']}} "
            f"{format_hours(rt.get('first_response_hours')):<{widths['first_resp']}} "
            f"{format_hours(rt.get('first_review_hours')):<{widths['first_rev']}} "
            f"{format_hours(rt.get('first_approval_hours')):<{widths['first_app']}} "
            f"{format_hours(pr.get('time_to_merge_hours')):<{widths['total']}} "
            f"{pr.get('total_lines_changed', 'N/A'):<{widths['lines']}}"
        )
        print(row)

    # Summary
    valid_response_times = [pr['response_times']['first_response_hours']
                           for pr in prs
                           if pr.get('response_times', {}).get('first_response_hours') is not None]

    if valid_response_times:
        print("\n" + "=" * len(header))
        print(f"Total PRs: {len(prs)}")
        print(f"Fastest first response: {format_hours(min(valid_response_times))} ({min(valid_response_times):.2f} hours)")
        print(f"Slowest first response: {format_hours(max(valid_response_times))} ({max(valid_response_times):.2f} hours)")
        print(f"Average first response: {format_hours(sum(valid_response_times)/len(valid_response_times))} ({sum(valid_response_times)/len(valid_response_times):.2f} hours)")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Sort PRs by time to first response (review, comment, or approval)'
    )
    parser.add_argument(
        'input_file',
        nargs='?',
        default='results.json',
        help='Input JSON file (default: results.json)'
    )
    parser.add_argument(
        '-s', '--sort',
        choices=['first_response', 'first_review', 'first_comment', 'first_approval', 'total_time'],
        default='first_response',
        help='Sort by field (default: first_response)'
    )
    parser.add_argument(
        '-a', '--ascending',
        action='store_true',
        help='Sort in ascending order (fastest first)'
    )
    parser.add_argument(
        '-f', '--format',
        choices=['text', 'csv', 'markdown'],
        default='text',
        help='Output format (default: text)'
    )
    parser.add_argument(
        '-n', '--limit',
        type=int,
        help='Limit number of results'
    )

    args = parser.parse_args()

    if not Path(args.input_file).exists():
        print(f"Error: Input file '{args.input_file}' not found", file=sys.stderr)
        sys.exit(1)

    # Read input
    with open(args.input_file, 'r') as f:
        data = json.load(f)

    prs = data.get('pull_requests', [])

    if not prs:
        print("Error: No PRs found in input file", file=sys.stderr)
        sys.exit(1)

    # Enrich with response times from the JSON data
    print(f"Processing {len(prs)} PRs with response time data...", file=sys.stderr)
    enriched_prs = enrich_prs_with_response_times(prs)

    # Print table
    print_table(enriched_prs, args.sort, args.ascending, args.format, args.limit)


if __name__ == '__main__':
    main()
