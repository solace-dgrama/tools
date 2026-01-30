#!/usr/bin/env python3
"""
Script to trim a file to contain only lines from the first to last occurrence
of a search string.
"""

import argparse
import sys


def trim_file(file_path, search_string):
    """
    Remove lines before first occurrence and after last occurrence of
    search_string in the file.

    Args:
        file_path: Path to the file to modify
        search_string: String to search for in each line
    """
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
    except IOError as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    # Find first and last occurrence
    first_index = None
    last_index = None

    for i, line in enumerate(lines):
        if search_string in line:
            if first_index is None:
                first_index = i
            last_index = i

    if first_index is None:
        print(
            f"String '{search_string}' not found in file",
            file=sys.stderr
        )
        sys.exit(1)

    # Extract lines from first to last occurrence (inclusive)
    trimmed_lines = lines[first_index:last_index + 1]

    # Write back to file
    try:
        with open(file_path, 'w') as f:
            f.writelines(trimmed_lines)
    except IOError as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Trimmed {file_path}: kept lines {first_index + 1} to "
        f"{last_index + 1} ({len(trimmed_lines)} lines)"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Trim file to lines between first and last occurrence "
                    "of a string"
    )
    parser.add_argument("file", help="File to modify")
    parser.add_argument("string", help="String to search for")

    args = parser.parse_args()

    trim_file(args.file, args.string)


if __name__ == "__main__":
    main()
