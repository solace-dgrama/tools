# PR Size Sorting Tool

## Overview
This tool analyzes and sorts pull requests from the `results.json` file by various metrics.

## Basic Usage

```bash
# Sort by total lines changed (largest first) - DEFAULT
./sort_prs_by_size.py

# Show top 20 PRs by size
./sort_prs_by_size.py -n 20

# Show top 10 PRs without statistics
./sort_prs_by_size.py -n 10 --no-stats
```

## Sorting Options

### By Lines Changed
```bash
# Total lines changed (additions + deletions)
./sort_prs_by_size.py --sort total_lines_changed -n 10

# By additions only
./sort_prs_by_size.py --sort additions -n 10

# By deletions only
./sort_prs_by_size.py --sort deletions -n 10
```

### By File Changes
```bash
# Number of files changed
./sort_prs_by_size.py --sort changed_files -n 10
```

### By Review Activity
```bash
# Number of reviews
./sort_prs_by_size.py --sort review_count -n 10

# Number of comments
./sort_prs_by_size.py --sort comment_count -n 10
```

### By Time
```bash
# Time to merge (longest first)
./sort_prs_by_size.py --sort time_to_merge_hours -n 10 --merged-only

# Shortest merge time first
./sort_prs_by_size.py --sort time_to_merge_hours -n 10 --reverse --merged-only
```

### By Commits
```bash
# Number of commits
./sort_prs_by_size.py --sort commits -n 10
```

## Filtering Options

### By Author
```bash
# Show PRs by specific author
./sort_prs_by_size.py --author solace-dgrama -n 20

# Case insensitive partial match
./sort_prs_by_size.py --author kourlas
```

### By State
```bash
# Show only merged PRs
./sort_prs_by_size.py --merged-only -n 20
```

## Sort Order

```bash
# Reverse sort order (smallest/shortest first)
./sort_prs_by_size.py --reverse -n 10
```

## Statistics

The tool displays overall statistics by default:
- Total PRs (merged vs closed)
- Total lines changed (additions/deletions)
- Total files changed
- Average lines per PR
- Average files per PR

To skip statistics:
```bash
./sort_prs_by_size.py --no-stats
```

## Output Format

The tool displays:
1. **Rank**: Position in sorted list
2. **PR #**: Pull request number
3. **Metric**: Value of the sort metric (lines, files, time, etc.)
4. **Files**: Number of changed files
5. **State**: MERGED or CLOSED
6. **Author**: PR author username
7. **Title**: PR title (truncated to fit)

## Common Use Cases

### Find the largest PRs
```bash
./sort_prs_by_size.py -n 20
```

### Find PRs that took longest to merge
```bash
./sort_prs_by_size.py --sort time_to_merge_hours --merged-only -n 20
```

### Find PRs with most file changes
```bash
./sort_prs_by_size.py --sort changed_files -n 20
```

### Find PRs with most review activity
```bash
./sort_prs_by_size.py --sort review_count -n 20
```

### Analyze a specific author's PRs
```bash
./sort_prs_by_size.py --author dgrama --merged-only
```

## Full Options Reference

```
-h, --help              Show help message
-f, --file FILE         Input JSON file (default: results.json)
-s, --sort METRIC       Metric to sort by
-n, --limit N           Show only top N results
-r, --reverse           Reverse sort order (smallest first)
--no-stats              Skip printing statistics
--merged-only           Show only merged PRs
--author NAME           Filter by author (case insensitive partial match)
```

### Available Sort Metrics
- `total_lines_changed` (default)
- `additions`
- `deletions`
- `changed_files`
- `commits`
- `time_to_merge_hours`
- `review_count`
- `comment_count`
