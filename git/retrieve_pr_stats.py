#!/usr/bin/env python3
"""
Script to retrieve GitHub PR information for a team within a date range.
Uses GitHub CLI (gh) to fetch PR data.
"""

import json
import subprocess
import sys
from datetime import datetime
from typing import List, Dict, Any
import argparse


def load_json_file(filepath: str) -> Dict:
    """Load and parse a JSON file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {filepath}: {e}")
        sys.exit(1)


def parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error: Invalid date format '{date_str}'. Expected YYYY-MM-DD: {e}")
        sys.exit(1)


def run_gh_command(args: List[str]) -> str:
    """Run a GitHub CLI command and return output."""
    try:
        result = subprocess.run(
            ['gh'] + args,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running gh command: {e}")
        print(f"stderr: {e.stderr}")
        return None
    except FileNotFoundError:
        print("Error: GitHub CLI (gh) not found. Please install it from https://cli.github.com/")
        sys.exit(1)


def is_bot_reviewer(reviewer_login: str) -> bool:
    """Check if a reviewer is a bot/AI (e.g., Copilot, github-actions)."""
    if not reviewer_login:
        return False

    reviewer_lower = reviewer_login.lower()
    bot_patterns = [
        'copilot',
        'github-actions',
        'dependabot',
        'renovate',
        'bot',
        '[bot]'
    ]

    return any(pattern in reviewer_lower for pattern in bot_patterns)


def get_pr_details(repo: str, pr_number: int) -> Dict[str, Any]:
    """Get detailed information about a specific PR."""
    pr_json = run_gh_command([
        'pr', 'view', str(pr_number),
        '--repo', repo,
        '--json', 'number,title,author,state,createdAt,mergedAt,closedAt,commits,additions,deletions,changedFiles,reviews,url,headRefName,baseRefName,labels,assignees,isDraft,comments'
    ])

    if pr_json:
        pr_data = json.loads(pr_json)

        # Fetch review timeline with timestamps using API
        # gh pr view doesn't include submittedAt for reviews, so we need to use the API
        reviews_json = run_gh_command([
            'api',
            f'repos/{repo}/pulls/{pr_number}/reviews',
            '--jq', '.'
        ])

        if reviews_json:
            pr_data['reviews_with_timestamps'] = json.loads(reviews_json)

        # Fetch comments timeline with timestamps
        comments_json = run_gh_command([
            'api',
            f'repos/{repo}/issues/{pr_number}/comments',
            '--jq', '.'
        ])

        if comments_json:
            pr_data['comments_with_timestamps'] = json.loads(comments_json)

        return pr_data
    return None


def list_prs_in_repo(repo: str, team_members: List[str] = None, start_date: datetime = None, end_date: datetime = None, state: str = 'all', limit: int = 1000) -> List[Dict]:
    """List PRs in a repository, optionally filtered by team members and date range."""
    cmd = ['pr', 'list', '--repo', repo, '--state', state, '--limit', str(limit)]

    # Build search query with authors and date filters
    search_parts = []

    # Add author filter
    if team_members:
        # Build search query: "author:user1 OR author:user2 OR author:user3"
        author_queries = [f"author:{member}" for member in team_members]
        author_query = " OR ".join(author_queries)
        # Wrap in parentheses if we have multiple authors
        if len(team_members) > 1:
            author_query = f"({author_query})"
        search_parts.append(author_query)

    # Add date range filter
    # Note: GitHub search doesn't support "created OR merged" in a single query,
    # so we use created date to narrow results and filter merged dates in Python
    if start_date and end_date:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        search_parts.append(f"created:>={start_str}")
        search_parts.append(f"created:<={end_str}")

    # Combine search parts
    if search_parts:
        search_query = " ".join(search_parts)
        cmd.extend(['--search', search_query])

    cmd.extend(['--json', 'number,title,author,state,createdAt,mergedAt'])

    pr_list_json = run_gh_command(cmd)

    if pr_list_json:
        return json.loads(pr_list_json)
    return []


def filter_prs_by_team_and_date(
    prs: List[Dict],
    team_members: List[str],
    start_date: datetime,
    end_date: datetime
) -> List[Dict]:
    """Filter PRs by team members and date range."""
    filtered_prs = []

    for pr in prs:
        # Check if author is in team
        author = pr.get('author', {}).get('login', '')
        if author not in team_members:
            continue

        # Check if PR was created or merged in the date range
        created_at = pr.get('createdAt')
        merged_at = pr.get('mergedAt')

        created_date = None
        merged_date = None

        if created_at:
            created_date = datetime.strptime(created_at[:10], "%Y-%m-%d")

        if merged_at:
            merged_date = datetime.strptime(merged_at[:10], "%Y-%m-%d")

        # Include PR if it was created or merged in the date range
        in_range = False
        if created_date and start_date <= created_date <= end_date:
            in_range = True
        if merged_date and start_date <= merged_date <= end_date:
            in_range = True

        if in_range:
            filtered_prs.append(pr)

    return filtered_prs


def fetch_team_members_from_github(org: str, team_slug: str) -> List[str]:
    """Fetch team members from GitHub using the API."""
    print(f"Fetching team members for '{team_slug}' from GitHub organization '{org}'...", file=sys.stderr)

    # Use GitHub API to get team members
    team_members_json = run_gh_command([
        'api',
        f'/orgs/{org}/teams/{team_slug}/members',
        '--jq', '.[].login'
    ])

    if team_members_json:
        members = [line.strip() for line in team_members_json.strip().split('\n') if line.strip()]
        print(f"Found {len(members)} members in GitHub team '{team_slug}'", file=sys.stderr)
        return members
    else:
        print(f"Warning: Could not fetch team members from GitHub. Check team name and permissions.", file=sys.stderr)
        return []


def get_pr_stats(repo: str, pr_numbers: List[int]) -> List[Dict[str, Any]]:
    """Get detailed statistics for a list of PRs."""
    pr_stats = []

    for pr_num in pr_numbers:
        print(f"  Fetching details for PR #{pr_num}...", file=sys.stderr)
        pr_details = get_pr_details(repo, pr_num)

        if pr_details:
            # Calculate review statistics (excluding bot/AI reviews)
            reviews = pr_details.get('reviews', [])
            # Filter out bot reviews
            human_reviews = [r for r in reviews if not is_bot_reviewer(r.get('author', {}).get('login', ''))]
            review_count = len(human_reviews)
            approvals = sum(1 for r in human_reviews if r.get('state') == 'APPROVED')
            changes_requested = sum(1 for r in human_reviews if r.get('state') == 'CHANGES_REQUESTED')

            # Calculate PR size metrics
            additions = pr_details.get('additions', 0)
            deletions = pr_details.get('deletions', 0)
            total_lines_changed = additions + deletions

            # Calculate time metrics
            created_at = pr_details.get('createdAt')
            merged_at = pr_details.get('mergedAt')
            closed_at = pr_details.get('closedAt')

            time_to_merge_hours = None
            if created_at and merged_at:
                created_dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                merged_dt = datetime.strptime(merged_at, "%Y-%m-%dT%H:%M:%SZ")
                time_to_merge_hours = (merged_dt - created_dt).total_seconds() / 3600

            # Get additional metadata
            labels = [label.get('name') for label in pr_details.get('labels', [])]
            assignees = [assignee.get('login') for assignee in pr_details.get('assignees', [])]
            is_draft = pr_details.get('isDraft', False)
            comment_count = len(pr_details.get('comments', []))

            # Calculate first response times
            first_comment_hours = None
            first_review_hours = None
            first_approval_hours = None
            first_response_hours = None

            if created_at:
                created_dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                earliest_times = []

                # Process reviews with timestamps (excluding bot/AI reviews)
                reviews_with_ts = pr_details.get('reviews_with_timestamps', [])
                for review in reviews_with_ts:
                    # Skip bot reviews
                    reviewer_login = review.get('user', {}).get('login', '')
                    if is_bot_reviewer(reviewer_login):
                        continue

                    submitted_at = review.get('submitted_at')
                    if submitted_at:
                        try:
                            # Handle different timestamp formats
                            if submitted_at.endswith('Z'):
                                review_dt = datetime.strptime(submitted_at, "%Y-%m-%dT%H:%M:%SZ")
                            else:
                                # Try ISO format with timezone
                                review_dt = datetime.fromisoformat(submitted_at.replace('Z', '+00:00'))
                                review_dt = review_dt.replace(tzinfo=None)  # Make naive for comparison

                            hours_to_review = (review_dt - created_dt).total_seconds() / 3600

                            # Track first review
                            if first_review_hours is None or hours_to_review < first_review_hours:
                                first_review_hours = hours_to_review

                            # Track first approval
                            if review.get('state') == 'APPROVED':
                                if first_approval_hours is None or hours_to_review < first_approval_hours:
                                    first_approval_hours = hours_to_review

                            earliest_times.append(hours_to_review)
                        except (ValueError, AttributeError) as e:
                            # Skip if we can't parse the timestamp
                            pass

                # Process comments with timestamps (excluding bot/AI comments)
                comments_with_ts = pr_details.get('comments_with_timestamps', [])
                for comment in comments_with_ts:
                    # Skip bot comments
                    commenter_login = comment.get('user', {}).get('login', '')
                    if is_bot_reviewer(commenter_login):
                        continue

                    comment_created = comment.get('created_at')
                    if comment_created:
                        try:
                            if comment_created.endswith('Z'):
                                comment_dt = datetime.strptime(comment_created, "%Y-%m-%dT%H:%M:%SZ")
                            else:
                                comment_dt = datetime.fromisoformat(comment_created.replace('Z', '+00:00'))
                                comment_dt = comment_dt.replace(tzinfo=None)

                            hours_to_comment = (comment_dt - created_dt).total_seconds() / 3600

                            # Track first comment
                            if first_comment_hours is None or hours_to_comment < first_comment_hours:
                                first_comment_hours = hours_to_comment

                            earliest_times.append(hours_to_comment)
                        except (ValueError, AttributeError) as e:
                            pass

                # First response is the earliest of any activity
                if earliest_times:
                    first_response_hours = min(earliest_times)

            # Build stats dictionary
            stats = {
                'repository': repo,
                'number': pr_details.get('number'),
                'title': pr_details.get('title'),
                'author': pr_details.get('author', {}).get('login'),
                'state': pr_details.get('state'),
                'url': pr_details.get('url'),
                'created_at': created_at,
                'merged_at': merged_at,
                'closed_at': closed_at,
                'time_to_merge_hours': round(time_to_merge_hours, 2) if time_to_merge_hours else None,
                'time_to_first_response_hours': round(first_response_hours, 2) if first_response_hours is not None else None,
                'time_to_first_comment_hours': round(first_comment_hours, 2) if first_comment_hours is not None else None,
                'time_to_first_review_hours': round(first_review_hours, 2) if first_review_hours is not None else None,
                'time_to_first_approval_hours': round(first_approval_hours, 2) if first_approval_hours is not None else None,
                'head_branch': pr_details.get('headRefName'),
                'base_branch': pr_details.get('baseRefName'),
                'commits': len(pr_details.get('commits', [])),
                'changed_files': pr_details.get('changedFiles'),
                'additions': additions,
                'deletions': deletions,
                'total_lines_changed': total_lines_changed,
                'review_count': review_count,
                'approvals': approvals,
                'changes_requested': changes_requested,
                'comment_count': comment_count,
                'is_draft': is_draft,
                'labels': labels,
                'assignees': assignees
            }
            pr_stats.append(stats)

    return pr_stats


def main():
    parser = argparse.ArgumentParser(
        description='Retrieve GitHub PR statistics for a team within a date range'
    )
    parser.add_argument(
        'config_file',
        help='Path to JSON configuration file'
    )
    parser.add_argument(
        '--team-file',
        default='team_members.json',
        help='Path to team members JSON file (default: team_members.json)'
    )
    parser.add_argument(
        '--output',
        default='pr_stats_output.json',
        help='Output JSON file path (default: pr_stats_output.json)'
    )
    parser.add_argument(
        '--fetch-team-from-github',
        action='store_true',
        help='Fetch team members from GitHub API instead of local file'
    )
    parser.add_argument(
        '--org',
        default='SolaceDev',
        help='GitHub organization name (default: SolaceDev, used with --fetch-team-from-github)'
    )

    args = parser.parse_args()

    # Load configuration
    print(f"Loading configuration from {args.config_file}...", file=sys.stderr)
    config = load_json_file(args.config_file)

    # Extract parameters
    start_date = parse_date(config['start_date'])
    end_date = parse_date(config['end_date'])
    team_name = config['team']
    repositories = config['repositories']
    org = config.get('organization', args.org)

    # Determine if we should fetch from GitHub
    # Priority: command line flag > config file setting > default (false)
    fetch_from_github = args.fetch_team_from_github or config.get('fetch_team_from_github', False)

    # Get team members - either from GitHub or local file
    if fetch_from_github:
        team_members = fetch_team_members_from_github(org, team_name)
        if not team_members:
            print(f"Error: Could not fetch team members from GitHub for team '{team_name}'", file=sys.stderr)
            print(f"Make sure you have access to the team and are authenticated with 'gh auth login'", file=sys.stderr)
            sys.exit(1)
    else:
        # Try to use team_members from config first, then fall back to team file
        if 'team_members' in config and config['team_members']:
            team_members = config['team_members']
            print(f"Using team members from config file: {len(team_members)} members", file=sys.stderr)
        else:
            print(f"Loading team members from {args.team_file}...", file=sys.stderr)
            team_data = load_json_file(args.team_file)

            if team_name not in team_data.get('teams', {}):
                print(f"Error: Team '{team_name}' not found in {args.team_file}", file=sys.stderr)
                print(f"Tip: Add 'fetch_team_from_github': true to your config file to fetch from GitHub", file=sys.stderr)
                sys.exit(1)

            team_members = team_data['teams'][team_name]['members']

    print(f"Team '{team_name}' has {len(team_members)} members: {', '.join(team_members)}", file=sys.stderr)
    print(f"Date range: {config['start_date']} to {config['end_date']}", file=sys.stderr)

    # Collect PR stats for all repositories
    all_pr_stats = []

    for repo in repositories:
        print(f"\nProcessing repository: {repo}", file=sys.stderr)

        # List PRs filtered by team members and date range
        print(f"Fetching PRs from {repo} for team members in date range...", file=sys.stderr)
        prs = list_prs_in_repo(repo, team_members=team_members, start_date=start_date, end_date=end_date)
        print(f"Found {len(prs)} PRs created by team members in date range", file=sys.stderr)

        # Filter to also include PRs merged (but not created) in date range
        filtered_prs = filter_prs_by_team_and_date(prs, team_members, start_date, end_date)
        print(f"Total {len(filtered_prs)} PRs (created or merged in date range)", file=sys.stderr)

        # Get detailed stats
        pr_numbers = [pr['number'] for pr in filtered_prs]
        if pr_numbers:
            pr_stats = get_pr_stats(repo, pr_numbers)
            all_pr_stats.extend(pr_stats)

    # Prepare output
    output_data = {
        'team': team_name,
        'start_date': config['start_date'],
        'end_date': config['end_date'],
        'repositories': repositories,
        'team_members': team_members,
        'total_prs': len(all_pr_stats),
        'pull_requests': all_pr_stats
    }

    # Write output
    print(f"\nWriting results to {args.output}...", file=sys.stderr)
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\nDone! Found {len(all_pr_stats)} PRs for team '{team_name}'", file=sys.stderr)
    print(f"Results written to: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
