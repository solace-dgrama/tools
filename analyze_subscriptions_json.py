#!/usr/bin/env python3
"""
Analyzes VPN subscriptions from JSON file and generates summary statistics.

The script categorizes subscriptions by VPN and topic type:
- Shared subscriptions starting with #share/
- Shared subscriptions starting with #noexport/#share/
- Other subscriptions

Outputs a summary file with counts of unique topics and totals per VPN.
"""

import json
import sys
import argparse
from collections import defaultdict


def analyze_subscriptions(input_file, detailed=False):
    """
    Analyze subscriptions from JSON file or stdin and print summary to stdout.

    Args:
        input_file: Path to input JSON file, '-' for stdin, or None for stdin
        detailed: If True, include detailed topic listings in output
    """
    # Parse JSON
    try:
        if input_file == '-' or input_file is None:
            data = json.load(sys.stdin)
        else:
            with open(input_file, 'r') as f:
                data = json.load(f)
    except Exception as e:
        print(f"Error parsing JSON file: {e}")
        sys.exit(1)

    # Data structure to hold VPN subscription data
    vpn_data = defaultdict(lambda: {
        'share_topics': defaultdict(int),
        'noexport_share_topics': defaultdict(int),
        'other_topics': defaultdict(int)
    })

    # Process all subscription entries
    subscriptions = data.get('subscriptions', [])

    for subscription_entry in subscriptions:
        vpn_name = subscription_entry.get('vpn_name')
        topic = subscription_entry.get('subscription')

        if vpn_name is None or topic is None:
            continue

        if topic.startswith('#noexport/#share/'):
            vpn_data[vpn_name]['noexport_share_topics'][topic] += 1
        elif topic.startswith('#share/'):
            vpn_data[vpn_name]['share_topics'][topic] += 1
        else:
            vpn_data[vpn_name]['other_topics'][topic] += 1

    # Calculate grand totals
    grand_total_share_unique = 0
    grand_total_share_count = 0
    grand_total_noexport_share_unique = 0
    grand_total_noexport_share_count = 0
    grand_total_other_unique = 0
    grand_total_other_count = 0
    grand_combined_shared_topics = defaultdict(int)

    for vpn_name in vpn_data.keys():
        data = vpn_data[vpn_name]
        grand_total_share_unique += len(data['share_topics'])
        grand_total_share_count += sum(data['share_topics'].values())
        grand_total_noexport_share_unique += len(data['noexport_share_topics'])
        grand_total_noexport_share_count += sum(data['noexport_share_topics'].values())
        grand_total_other_unique += len(data['other_topics'])
        grand_total_other_count += sum(data['other_topics'].values())

        # Calculate combined shared for grand totals
        for topic, count in data['share_topics'].items():
            value_x = topic.replace('#share/', '', 1)
            grand_combined_shared_topics[value_x] += count
        for topic, count in data['noexport_share_topics'].items():
            value_x = topic.replace('#noexport/#share/', '', 1)
            grand_combined_shared_topics[value_x] += count

    grand_combined_shared_unique = len(grand_combined_shared_topics)
    grand_combined_shared_total = sum(grand_combined_shared_topics.values())

    # Print summary to stdout
    print("=" * 80)
    print("VPN SUBSCRIPTION SUMMARY")
    print("=" * 80)
    print()

    # Sort VPNs alphabetically for consistent output
    for vpn_name in sorted(vpn_data.keys()):
        data = vpn_data[vpn_name]

        share_unique = len(data['share_topics'])
        share_total = sum(data['share_topics'].values())
        noexport_share_unique = len(data['noexport_share_topics'])
        noexport_share_total = sum(data['noexport_share_topics'].values())
        other_unique = len(data['other_topics'])
        other_total = sum(data['other_topics'].values())

        # Calculate combined shared subscriptions (treating #share/X and #noexport/#share/X as same)
        combined_shared_topics = defaultdict(int)
        for topic, count in data['share_topics'].items():
            value_x = topic.replace('#share/', '', 1)
            combined_shared_topics[value_x] += count
        for topic, count in data['noexport_share_topics'].items():
            value_x = topic.replace('#noexport/#share/', '', 1)
            combined_shared_topics[value_x] += count

        combined_shared_unique = len(combined_shared_topics)
        combined_shared_total = sum(combined_shared_topics.values())

        total_unique = share_unique + noexport_share_unique + other_unique
        total_count = share_total + noexport_share_total + other_total

        print(f"VPN: {vpn_name}")
        print("-" * 80)
        print(f"  Unique #share/ subscriptions:              {share_unique:>6}  (total: {share_total})")
        print(f"  Unique #noexport/#share/ subscriptions:    {noexport_share_unique:>6}  (total: {noexport_share_total})")
        print(f"    Unique shared (combined):                {combined_shared_unique:>6}  (total: {combined_shared_total})")
        print(f"  Unique other subscriptions:                {other_unique:>6}  (total: {other_total})")
        print(f"  " + "-" * 76)
        print(f"  TOTAL subscriptions:                       {total_unique:>6}  (total: {total_count})")
        print()

        # List the unique topics with counts (only if detailed mode)
        if detailed:
            if share_unique > 0:
                print(f"  Unique #share/ topics ({share_unique}):")
                for topic in sorted(data['share_topics'].keys()):
                    count = data['share_topics'][topic]
                    print(f"    {count:>6}: {topic}")
                print()

            if noexport_share_unique > 0:
                print(f"  Unique #noexport/#share/ topics ({noexport_share_unique}):")
                for topic in sorted(data['noexport_share_topics'].keys()):
                    count = data['noexport_share_topics'][topic]
                    print(f"    {count:>6}: {topic}")
                print()

            if other_unique > 0:
                print(f"  Unique other topics ({other_unique}):")
                for topic in sorted(data['other_topics'].keys()):
                    count = data['other_topics'][topic]
                    print(f"    {count:>6}: {topic}")
                print()

    # Grand totals section
    print("=" * 80)
    print("GRAND TOTALS (ALL VPNs)")
    print("=" * 80)
    print(f"  Unique #share/ subscriptions:              {grand_total_share_unique:>6}  (total: {grand_total_share_count})")
    print(f"  Unique #noexport/#share/ subscriptions:    {grand_total_noexport_share_unique:>6}  (total: {grand_total_noexport_share_count})")
    print(f"    Unique shared (combined):                {grand_combined_shared_unique:>6}  (total: {grand_combined_shared_total})")
    print(f"  Unique other subscriptions:                {grand_total_other_unique:>6}  (total: {grand_total_other_count})")
    print(f"  " + "-" * 76)
    grand_total_unique_all = grand_total_share_unique + grand_total_noexport_share_unique + grand_total_other_unique
    grand_total_all = grand_total_share_count + grand_total_noexport_share_count + grand_total_other_count
    print(f"  TOTAL subscriptions:                       {grand_total_unique_all:>6}  (total: {grand_total_all})")
    print()
    print("=" * 80)
    print("END OF SUMMARY")
    print("=" * 80)



def main():
    parser = argparse.ArgumentParser(
        description='Analyze VPN subscriptions from JSON file or stdin',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Read from file
  python analyze_subscriptions_json.py bb.txt
  python analyze_subscriptions_json.py bb.txt --detail
  python analyze_subscriptions_json.py bb.txt -d
  python analyze_subscriptions_json.py bb.txt > summary.txt
  python analyze_subscriptions_json.py bb.txt -d > summary_detailed.txt

  # Read from stdin (pipe)
  ./parse_vpn_subscriptions.py input.txt | ./analyze_subscriptions_json.py
  ./parse_vpn_subscriptions.py input.txt | ./analyze_subscriptions_json.py -d
  ./parse_vpn_subscriptions.py input.txt | ./analyze_subscriptions_json.py - --detail
        '''
    )
    parser.add_argument('input_file', nargs='?', default='-',
                        help='Path to input JSON file (use "-" or omit for stdin)')
    parser.add_argument('-d', '--detail', action='store_true',
                        help='Include detailed topic listings in output')

    args = parser.parse_args()

    analyze_subscriptions(args.input_file, args.detail)


if __name__ == "__main__":
    main()
