# GitHub PR Statistics Retrieval Script

This script retrieves GitHub Pull Request statistics for a specific team within a date range.

## Prerequisites

- Python 3.6+
- GitHub CLI (`gh`) installed and authenticated
  - Install: https://cli.github.com/
  - Authenticate: `gh auth login`

## Files

1. **retrieve_pr_stats.py** - Main script
2. **team_members.json** - Team member configuration
3. **pr_config_example.json** - Example configuration file

## Configuration

### Team Members

The script supports two modes for specifying team members:

#### Option 1: Fetch from GitHub (Recommended)

Use the `--fetch-team-from-github` flag to automatically retrieve team members from GitHub:

```bash
./retrieve_pr_stats.py pr_config.json --fetch-team-from-github
```

This requires:
- A GitHub account with access to view the team members
- Proper authentication with `gh auth login`
- The team name specified in the config file must match the GitHub team slug

#### Option 2: Local Configuration File (team_members.json)

Define your teams and their GitHub usernames manually:

```json
{
  "teams": {
    "ebp-routing": {
      "members": [
        "github-username1",
        "github-username2",
        "github-username3"
      ]
    }
  }
}
```

### PR Configuration File

Specify the date range, team, organization, and repositories:

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "team": "ebp-routing",
  "organization": "SolaceDev",
  "repositories": [
    "SolaceDev/broker"
  ]
}
```

Fields:
- `start_date`: Start date in YYYY-MM-DD format
- `end_date`: End date in YYYY-MM-DD format
- `team`: GitHub team slug (e.g., "ebp-routing")
- `organization`: GitHub organization name (optional, defaults to "SolaceDev")
- `repositories`: List of repositories in "owner/repo" format

## Usage

Basic usage with local team file:

```bash
./retrieve_pr_stats.py pr_config_example.json
```

Fetch team members from GitHub (recommended):

```bash
./retrieve_pr_stats.py pr_config_example.json --fetch-team-from-github
```

With custom team file and output:

```bash
./retrieve_pr_stats.py pr_config_example.json \
  --team-file team_members.json \
  --output my_pr_stats.json
```

Fetch from GitHub with custom organization and output:

```bash
./retrieve_pr_stats.py pr_config_example.json \
  --fetch-team-from-github \
  --org SolaceDev \
  --output my_pr_stats.json
```

### Command-line Arguments

- `config_file` (required) - Path to JSON configuration file
- `--team-file` (optional) - Path to team members JSON file (default: team_members.json)
- `--output` (optional) - Output JSON file path (default: pr_stats_output.json)
- `--fetch-team-from-github` (optional) - Fetch team members from GitHub API instead of local file
- `--org` (optional) - GitHub organization name (default: SolaceDev, used with --fetch-team-from-github)

## Output Format

The script generates a JSON file with the following structure:

```json
{
  "team": "ebp-routing",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "repositories": ["SolaceDev/broker"],
  "team_members": ["user1", "user2"],
  "total_prs": 5,
  "pull_requests": [
    {
      "repository": "SolaceDev/broker",
      "number": 123,
      "title": "Fix routing bug",
      "author": "user1",
      "state": "MERGED",
      "url": "https://github.com/SolaceDev/broker/pull/123",
      "created_at": "2026-01-15T10:30:00Z",
      "merged_at": "2026-01-16T14:20:00Z",
      "closed_at": "2026-01-16T14:20:00Z",
      "time_to_merge_hours": 27.83,
      "head_branch": "feature-branch",
      "base_branch": "main",
      "commits": 3,
      "changed_files": 5,
      "additions": 120,
      "deletions": 45,
      "total_lines_changed": 165,
      "review_count": 2,
      "approvals": 2,
      "changes_requested": 0,
      "comment_count": 5,
      "is_draft": false,
      "labels": ["bug", "urgent"],
      "assignees": ["user1"]
    }
  ]
}
```

## Statistics Included

For each PR, the following statistics are collected:

### Basic Information
- Repository name
- PR number and title
- Author
- State (OPEN, CLOSED, MERGED)
- URL
- Draft status

### Time Metrics
- Created timestamp
- Merged timestamp
- Closed timestamp
- Time to merge (in hours)

### Code Metrics
- Number of commits
- Number of changed files
- Line additions
- Line deletions
- **Total lines changed (PR size)** - sum of additions + deletions

### Review Metrics
- Number of reviews
- Number of approvals
- Number of change requests
- Number of comments

### Metadata
- Source and target branches
- Labels
- Assignees

## Filtering Logic

PRs are included if:
1. The author is a member of the specified team
2. The PR was either created OR merged within the specified date range

## Example Workflows

### Workflow 1: Using GitHub API (Recommended)

1. Ensure you're authenticated with GitHub CLI: `gh auth login`
2. Create a config file with your desired date range, team, and repositories
3. Run the script with team fetching enabled:
   ```bash
   ./retrieve_pr_stats.py my_config.json --fetch-team-from-github --output results.json
   ```
4. Review the results in `results.json`

### Workflow 2: Using Local Team File

1. Update `team_members.json` with your team's GitHub usernames
2. Create a config file with your desired date range and repositories
3. Run the script:
   ```bash
   ./retrieve_pr_stats.py my_config.json --output results.json
   ```
4. Review the results in `results.json`

## Troubleshooting

- **"gh command not found"**: Install GitHub CLI from https://cli.github.com/
- **Authentication errors**: Run `gh auth login` to authenticate
- **Rate limiting**: The script may be slow for large repositories due to GitHub API rate limits
