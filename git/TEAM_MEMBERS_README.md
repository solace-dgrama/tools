# Dynamic Team Member Fetching

## Overview

The `retrieve_pr_stats.py` script now supports automatically fetching team members from GitHub, eliminating the need to maintain a separate team members file.

## What Changed

The script now supports **three ways** to specify team members:

1. **Fetch from GitHub (Recommended)** - Automatically fetches current team members
2. **Inline in config file** - Specify team members directly in the config
3. **Separate team file** - Use the old team_members.json file (legacy)

## Method 1: Auto-Fetch from GitHub (Recommended)

### Configuration

Add `"fetch_team_from_github": true` to your config file:

```json
{
  "start_date": "2025-11-01",
  "end_date": "2026-01-31",
  "team": "ebp-routing",
  "organization": "SolaceDev",
  "fetch_team_from_github": true,
  "repositories": [
    "SolaceDev/broker"
  ]
}
```

### Usage

```bash
# Simply run with your config - it will automatically fetch team members
python3 retrieve_pr_stats.py pr_config_auto_team.json --output results.json
```

### Benefits

✅ Always up-to-date with GitHub team membership
✅ No need to maintain separate team files
✅ Automatically includes new team members
✅ Automatically excludes members who left

### Requirements

- You must be authenticated with GitHub CLI: `gh auth login`
- You must have access to view the team in the organization
- Internet connection required

## Method 2: Inline Team Members

Specify team members directly in the config file:

```json
{
  "start_date": "2025-11-01",
  "end_date": "2026-01-31",
  "team": "ebp-routing",
  "organization": "SolaceDev",
  "team_members": [
    "ZehongZhan",
    "kurultai",
    "solace-kpaulson",
    "solace-dgrama",
    "fchan-solace",
    "solace-mkourlas",
    "solace-wkourlas"
  ],
  "repositories": [
    "SolaceDev/broker"
  ]
}
```

This method works offline but requires manual updates.

## Method 3: Separate Team File (Legacy)

The old method still works - use a separate team_members.json file:

```bash
python3 retrieve_pr_stats.py pr_config.json --team-file team_members.json --output results.json
```

## Current Team Members (as of fetch)

When using `fetch_team_from_github: true`, the script found:

```
ebp-routing team members (7):
- ZehongZhan
- kurultai
- solace-kpaulson
- solace-dgrama
- fchan-solace
- solace-mkourlas
- solace-wkourlas
```

## Command Line Override

You can also use the command line flag to override the config:

```bash
# Force fetch from GitHub even if not in config
python3 retrieve_pr_stats.py pr_config.json --fetch-team-from-github --output results.json

# Specify a different organization
python3 retrieve_pr_stats.py pr_config.json --fetch-team-from-github --org SolaceDev --output results.json
```

## Troubleshooting

### Error: "Could not fetch team members from GitHub"

**Possible causes:**

1. **Not authenticated**: Run `gh auth login` first
2. **No access to team**: Make sure you're a member or have permission to view the team
3. **Wrong team name**: Verify the team slug is correct (use `gh api orgs/SolaceDev/teams` to list teams)
4. **Wrong organization**: Check the organization name in your config

### Error: "Team not found in team_members.json"

If not using `fetch_team_from_github`, add the team to your team file or use Method 1 or 2 above.

## Recommendation

For the ebp-routing team, use **Method 1** (auto-fetch from GitHub) by:

1. Use the `pr_config_auto_team.json` config file (already created)
2. Or add `"fetch_team_from_github": true` to your existing config

This ensures you always have the current team membership without manual updates!
