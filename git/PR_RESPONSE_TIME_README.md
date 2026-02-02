# PR Response Time Analysis

This document explains how to use the updated PR statistics scripts to analyze review response times.

## Overview

The scripts have been updated to collect and display:
- **Time to First Response**: Earliest of any comment or review
- **Time to First Comment**: When the first comment was made
- **Time to First Review**: When the first review was submitted
- **Time to First Approval**: When the PR was first approved
- **Total Time to Merge**: Total time from creation to merge

## Step 1: Collect PR Data with Response Times

Use `retrieve_pr_stats.py` to fetch PR data including response times:

```bash
# Use your existing config file
python3 retrieve_pr_stats.py pr_config.json --output results_with_response_times.json
```

The script will now:
1. Fetch basic PR information
2. Fetch review timeline with timestamps
3. Fetch comment timeline with timestamps
4. Calculate all response time metrics

**Note**: This will take longer than before because it makes additional API calls for each PR to get the detailed timeline data.

## Step 2: Display Results in Table Format

Use `sort_prs_table.py` to display the results:

### Sort by First Response Time (Fastest responders)
```bash
python3 sort_prs_table.py results_with_response_times.json -s first_response -a -n 20
```

### Sort by First Response Time (Slowest to respond)
```bash
python3 sort_prs_table.py results_with_response_times.json -s first_response -n 20
```

### Sort by First Approval Time
```bash
python3 sort_prs_table.py results_with_response_times.json -s first_approval -a -n 20
```

### Sort by Total Review Time (original behavior)
```bash
python3 sort_prs_table.py results_with_response_times.json -s review_time -n 20
```

## Available Sort Options

- `first_response` - Time to first response (comment or review)
- `first_comment` - Time to first comment
- `first_review` - Time to first review
- `first_approval` - Time to first approval
- `review_time` - Total time to merge (default)
- `size` - Lines changed
- `reviews` - Number of reviews
- `number` - PR number
- `created` - Creation date

## Output Formats

### Text Table (default)
```bash
python3 sort_prs_table.py results_with_response_times.json
```

Shows nicely formatted table with all timing columns.

### CSV (for Excel/Sheets)
```bash
python3 sort_prs_table.py results_with_response_times.json --format csv > pr_response_times.csv
```

### Markdown (for documentation)
```bash
python3 sort_prs_table.py results_with_response_times.json --format markdown > PR_REPORT.md
```

## Example Usage

```bash
# Step 1: Fetch data (this will take a while - fetches timeline for all PRs)
python3 retrieve_pr_stats.py pr_config.json --output results.json

# Step 2: View fastest first responses (top 20)
python3 sort_prs_table.py results.json -s first_response -a -n 20

# Step 3: Export to CSV for detailed analysis
python3 sort_prs_table.py results.json --format csv > pr_analysis.csv
```

## Understanding the Output

**Text Table Columns:**
- **PR#**: Pull request number
- **Title**: PR title (truncated)
- **Author**: GitHub username
- **First Resp**: Time to any response (comment/review)
- **First Rev**: Time to first review
- **First App**: Time to first approval
- **Total Time**: Time from creation to merge
- **Lines**: Total lines changed
- **Reviews**: Number of reviews

**Summary Statistics** show:
- Total/merged PR counts
- Min/max/average total time to merge
- Min/max/average time to first response

## Notes

- **N/A** values indicate:
  - PR wasn't merged (for Total Time)
  - No responses/reviews/approvals received (for response times)
- Times are displayed as:
  - Minutes (m) if < 1 hour
  - Hours (h) if < 24 hours
  - Days (d) if >= 24 hours
- The `-a` flag sorts in ascending order (fastest first)
- Without `-a`, sorts in descending order (slowest first)
