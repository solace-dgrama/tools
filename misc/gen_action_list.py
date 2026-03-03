#!/usr/bin/env python3
"""
gen_action_list.py — standalone chaotic-mode action list generator.

Replicates the action list builder from reg_vmrRedundancyRandomActions.tcl
without requiring the AFW framework or any broker connectivity.  Output is
the same comma-separated format produced by the script when run with
-generateActionListOnly 1.

Usage:
    ./gen_action_list.py [options]
    ./gen_action_list.py | ./validate_action_list.py -

Options mirror the corresponding -scriptArgs parameters:
    --subset            Comma-separated action names, or 'all' (default: all)
    --max-before-check  Max actions per group before check (default: 30)
    --max-total         Stop after this many total list items (default: 200)
    --min-sleep         Minimum sleep value in seconds (default: 15)
    --max-sleep         Maximum sleep value in seconds (default: 30)
    --external-disk-ip  Enable externalDiskLinkDown/LinkNetemAdd actions
    --pubsub-permanent-netem      Suppress pubsubLinkNetemAdd
    --external-disk-permanent-netem  Suppress externalDiskLinkNetemAdd
    --seed              Fix the random seed for reproducibility

Exit codes:
    0  success
    2  argument error
"""

import argparse
import random
import sys
from collections import defaultdict
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_TARGETS: List[str] = ["primary", "backup", "monitor"]

# Maps each do-action to its recovery action ("" means no recovery needed).
UNDO: Dict[str, str] = {
    "isolateNode":                   "recoverNode",
    "powerDown":                     "powerUp",
    "ungracefulPowerDown":           "ungracefulPowerUp",
    "reload":                        "",
    "cpuHog":                        "",
    "linkDown":                      "linkUp",
    "mateLinkDown":                  "mateLinkUp",
    "consulLinkDown":                "consulLinkUp",
    "messageSpoolDisable":           "messageSpoolEnable",
    "redundancyDisable":             "redundancyEnable",
    "messageBackboneServiceDisable": "messageBackboneServiceEnable",
    "mateLinkServiceDisable":        "mateLinkServiceEnable",
    "redundancyServiceDisable":      "redundancyServiceEnable",
    "externalDiskLinkNetemAdd":      "externalDiskLinkNetemRemove",
    "linkNetemAdd":                  "linkNetemRemove",
    "pubsubLinkNetemAdd":            "pubsubLinkNetemRemove",
    "externalDiskLinkDown":          "externalDiskLinkUp",
    "consulDown":                    "consulUp",
}

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_item(raw: str):
    """Split 'action:targets:value' into (action, targets_list, value)."""
    parts = raw.split(":")
    action = parts[0] if parts else ""
    targets_str = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""
    return action, [t for t in targets_str.split("-") if t], value


# ---------------------------------------------------------------------------
# Forward-scan helper (HasActionOnTargetBeforeRecovery)
# ---------------------------------------------------------------------------

def _has_action_before_recovery(
    action_list: List[str],
    start_idx: int,
    targets: List[str],
    recovery_action: str,
) -> bool:
    """
    Returns True if, for any target in targets, the do-action on that target
    appears in action_list at or after start_idx before the recovery_action
    for that target.  Replicates HasActionOnTargetBeforeRecovery from Tcl.
    """
    for target in targets:
        for i in range(start_idx, len(action_list)):
            fwd_action, fwd_targets, _ = _parse_item(action_list[i])
            if target in fwd_targets:
                if fwd_action == recovery_action:
                    break
                return True
    return False


# ---------------------------------------------------------------------------
# Flag management
# ---------------------------------------------------------------------------

Flags = Dict[str, Dict[str, bool]]


def _new_flags(do_targets: List[str]) -> Flags:
    """Create zero-initialised flags for the given DO-action targets."""
    init = {t: False for t in do_targets}
    return {
        "power_down": defaultdict(bool, init),
        "ungraceful":  defaultdict(bool, init),
        "isolated":    defaultdict(bool, init),
        "disk_down":   defaultdict(bool, init),
        "skip":        defaultdict(bool, init),
    }


def _do_scan_update_flags(
    action: str, item_targets: List[str], flags: Flags
) -> None:
    """
    Update flags for one item in the DO scan.

    Node-isolation setters/clearers use ALL_TARGETS (allTargetsList in Tcl).
    Note: the Tcl DO scan spells linkDown's recovery as 'LinkUp' (capital L),
    so 'linkUp' (the actual recovery action) falls to the else branch and
    never clears isolated in the DO scan.  This behaviour is preserved here.
    """
    if action == "powerDown":
        for t in item_targets:
            flags["power_down"][t] = True
            flags["skip"][t] = False
    elif action == "powerUp":
        for t in item_targets:
            flags["power_down"][t] = False
            flags["skip"][t] = True
    elif action == "ungracefulPowerDown":
        for t in item_targets:
            flags["ungraceful"][t] = True
            flags["skip"][t] = False
    elif action == "ungracefulPowerUp":
        for t in item_targets:
            flags["ungraceful"][t] = False
            flags["skip"][t] = True
    elif action in (
        "messageSpoolDisable", "redundancyDisable",
        "messageBackboneServiceDisable", "redundancyServiceDisable",
        "linkDown", "mateLinkServiceDisable", "mateLinkDown",
    ):
        for t in ALL_TARGETS:
            flags["isolated"][t] = True
            flags["skip"][t] = False
    elif action in (
        "messageSpoolEnable", "redundancyEnable",
        "messageBackboneServiceEnable", "redundancyServiceEnable",
        "LinkUp",  # capital-L typo from Tcl DO scan — linkUp never matches
        "mateLinkServiceEnable", "mateLinkUp",
    ):
        for t in ALL_TARGETS:
            flags["isolated"][t] = False
            flags["skip"][t] = True
    elif action == "externalDiskLinkDown":
        for t in item_targets:
            flags["disk_down"][t] = True
            flags["skip"][t] = False
    elif action == "externalDiskLinkUp":
        for t in item_targets:
            flags["disk_down"][t] = False
            flags["skip"][t] = True
    elif action == "isolateNode":
        for t in item_targets:
            flags["isolated"][t] = True
            flags["skip"][t] = False
    elif action == "recoverNode":
        for t in item_targets:
            flags["isolated"][t] = False
            flags["skip"][t] = True
    else:
        for t in item_targets:
            flags["skip"][t] = False


def _undo_scan_update_flags(
    action: str, item_targets: List[str], flags: Flags
) -> None:
    """
    Update flags for one item in the UNDO scan.

    Uses per-item targets only (no allTargetsList).  'linkUp' is correctly
    lowercased here (unlike the DO scan).
    messageSpoolDisable/Enable and messageBackboneServiceDisable/Enable are
    absent from the Tcl UNDO scan and fall to the else branch.
    """
    if action == "powerDown":
        for t in item_targets:
            flags["power_down"][t] = True
            flags["skip"][t] = False
    elif action == "ungracefulPowerDown":
        for t in item_targets:
            flags["ungraceful"][t] = True
            flags["skip"][t] = False
    elif action == "powerUp":
        for t in item_targets:
            flags["power_down"][t] = False
            flags["skip"][t] = True
    elif action == "ungracefulPowerUp":
        for t in item_targets:
            flags["ungraceful"][t] = False
            flags["skip"][t] = True
    elif action in (
        "redundancyDisable", "redundancyServiceDisable",
        "linkDown", "mateLinkServiceDisable", "mateLinkDown",
    ):
        for t in item_targets:
            flags["isolated"][t] = True
            flags["skip"][t] = False
    elif action in (
        "redundancyEnable", "redundancyServiceEnable",
        "linkUp", "mateLinkServiceEnable", "mateLinkUp",
    ):
        for t in item_targets:
            flags["isolated"][t] = False
            flags["skip"][t] = True
    elif action == "externalDiskLinkDown":
        for t in item_targets:
            flags["disk_down"][t] = True
            flags["skip"][t] = False
    elif action == "externalDiskLinkUp":
        for t in item_targets:
            flags["disk_down"][t] = False
            flags["skip"][t] = True
    elif action == "isolateNode":
        for t in item_targets:
            flags["isolated"][t] = True
            flags["skip"][t] = False
    elif action == "recoverNode":
        for t in item_targets:
            flags["isolated"][t] = False
            flags["skip"][t] = True
    else:
        for t in item_targets:
            flags["skip"][t] = False


# ---------------------------------------------------------------------------
# Insertion-point allow checks
# ---------------------------------------------------------------------------

def _do_allowed(
    do_action: str, do_targets: List[str], flags: Flags
) -> bool:
    """Return True if inserting do_action at the current scan position is valid."""
    if do_action == "":
        return False
    if do_action in ("powerDown", "ungracefulPowerDown"):
        return all(
            not flags["skip"][t]
            and not flags["ungraceful"][t]
            and not flags["power_down"][t]
            for t in do_targets
        )
    if do_action == "reload":
        return all(
            not flags["skip"][t]
            and not flags["power_down"][t]
            and not flags["ungraceful"][t]
            and not flags["disk_down"][t]
            for t in do_targets
        )
    if do_action == "externalDiskLinkDown":
        return all(
            not flags["skip"][t] and not flags["disk_down"][t]
            for t in do_targets
        )
    if do_action in (
        "redundancyDisable", "messageBackboneServiceDisable",
        "redundancyServiceDisable", "messageSpoolDisable",
        "linkDown", "mateLinkServiceDisable", "mateLinkDown",
    ):
        return all(
            not flags["skip"][t]
            and not flags["power_down"][t]
            and not flags["ungraceful"][t]
            and not flags["isolated"][t]
            for t in do_targets
        )
    # Generic: cannot act on powered-down or isolated target.
    return all(
        not flags["skip"][t]
        and not flags["power_down"][t]
        and not flags["isolated"][t]
        and not flags["ungraceful"][t]
        for t in do_targets
    )


def _undo_allowed(
    undo_action: str, do_action: str, do_targets: List[str], flags: Flags
) -> bool:
    """Return True if inserting undo_action at the current UNDO scan position is valid."""
    if do_action in ("reload", ""):
        return False
    if undo_action == "powerUp":
        return all(
            not flags["skip"][t]
            and not flags["ungraceful"][t]
            and flags["power_down"][t]      # target must be powered down
            and not flags["disk_down"][t]
            for t in do_targets
        )
    if undo_action == "ungracefulPowerUp":
        return all(
            not flags["skip"][t]
            and flags["ungraceful"][t]       # target must be ungracefully down
            and not flags["disk_down"][t]
            for t in do_targets
        )
    if undo_action == "externalDiskLinkUp":
        return all(
            not flags["skip"][t]
            and flags["disk_down"][t]        # target must have disk down
            for t in do_targets
        )
    # Generic: cannot recover on a powered-down or ungracefully-down target.
    return all(
        not flags["skip"][t]
        and not flags["power_down"][t]
        and not flags["ungraceful"][t]
        for t in do_targets
    )


# ---------------------------------------------------------------------------
# Candidate action list builder
# ---------------------------------------------------------------------------

def build_do_action_list(
    subset,
    external_disk_ip: str,
    pubsub_permanent_netem: bool,
    external_disk_permanent_netem: bool,
) -> List[str]:
    """
    Build the list of 'action:targets:' candidate entries, matching the Tcl
    builder exactly (single/double/triple target enumeration, subset filter,
    duplicate-pair prevention).
    """
    subset_set: Optional[set] = None if subset == "all" else set(subset)

    def included(action: str) -> bool:
        return subset_set is None or action in subset_set

    do_list: List[str] = []

    # Single-target actions on primary / backup / monitor
    for a in [
        "powerDown", "ungracefulPowerDown", "redundancyDisable",
        "redundancyServiceDisable", "reload", "linkNetemAdd",
        "consulDown", "cpuHog",
    ]:
        if included(a):
            for t in ["primary", "backup", "monitor"]:
                do_list.append(f"{a}:{t}:")

    # isolateNode: monitor only
    if included("isolateNode"):
        do_list.append("isolateNode:monitor:")

    # Single-target actions on primary / backup only
    for a in [
        "messageSpoolDisable", "mateLinkServiceDisable",
        "messageBackboneServiceDisable",
    ]:
        if included(a):
            for t in ["primary", "backup"]:
                do_list.append(f"{a}:{t}:")

    # externalDiskLinkDown: only when an external disk IP is configured
    if included("externalDiskLinkDown") and external_disk_ip:
        for t in ["primary", "backup"]:
            do_list.append(f"externalDiskLinkDown:{t}:")

    # externalDiskLinkNetemAdd: only when IP is set and netem not permanent
    if (
        included("externalDiskLinkNetemAdd")
        and external_disk_ip
        and not external_disk_permanent_netem
    ):
        do_list.append(f"externalDiskLinkNetemAdd:{external_disk_ip}:")

    # pubsubLinkNetemAdd: only when not already permanently applied
    if included("pubsubLinkNetemAdd") and not pubsub_permanent_netem:
        do_list.append("pubsubLinkNetemAdd::")

    # Double-target: linkDown and consulLinkDown (primary/backup, no reverse-dup)
    for a in ["linkDown", "consulLinkDown"]:
        if included(a):
            for t1 in ["primary", "backup"]:
                for t2 in ["primary", "backup"]:
                    if t1 != t2 and f"{a}:{t2}-{t1}:" not in do_list:
                        do_list.append(f"{a}:{t1}-{t2}:")

    # Double-target: mateLinkDown (primary/backup, no reverse-dup)
    if included("mateLinkDown"):
        for t1 in ["primary", "backup"]:
            for t2 in ["primary", "backup"]:
                if t1 != t2 and f"mateLinkDown:{t2}-{t1}:" not in do_list:
                    do_list.append(f"mateLinkDown:{t1}-{t2}:")

    # Triple-target: reload all three nodes at once
    if included("reload"):
        do_list.append("reload:primary-backup-monitor:")

    return do_list


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate(
    do_action_list: List[str],
    max_actions_total: int,
    max_actions_before_check: int,
    min_sleep: int,
    max_sleep: int,
) -> List[str]:
    """
    Generate the chaotic action list.

    Replicates the two nested while-loops from the Tcl 'chaotic' switch arm,
    including the exact flag-update ordering (DO scan: check-first; UNDO scan:
    update-first) and the fallback UNDO insertion at do_index+1 when no valid
    UNDO position is found.
    """
    action_list: List[str] = []
    list_of_actions_number = 0

    while len(action_list) <= max_actions_total:
        current_action_list: List[str] = []

        while len(current_action_list) <= max_actions_before_check:
            current_do = random.choice(do_action_list)
            current_do_action, current_do_targets, current_do_value = (
                _parse_item(current_do)
            )
            current_undo_action = UNDO.get(current_do_action, "")

            flags = _new_flags(current_do_targets)

            # --- DO scan: find valid insertion positions ---
            allowed_do: List[int] = []
            for x in range(len(current_action_list)):
                item_action, item_targets, _ = _parse_item(
                    current_action_list[x]
                )
                # Check rules first (before updating flags for item x).
                # Universal repeat-prevention: reject if the same do-action
                # already appears on any of the targets ahead without its
                # recovery in between.
                if current_undo_action and _has_action_before_recovery(
                    current_action_list, x,
                    current_do_targets, current_undo_action,
                ):
                    pass  # position rejected
                elif _do_allowed(current_do_action, current_do_targets, flags):
                    allowed_do.append(x)
                # Then update flags for the existing item at x.
                _do_scan_update_flags(item_action, item_targets, flags)

            # Post-loop: check appending at the end of the list.
            # (HasActionOnTargetBeforeRecovery at start_idx==len returns False.)
            if _do_allowed(current_do_action, current_do_targets, flags):
                allowed_do.append(len(current_action_list))

            if not allowed_do:
                continue  # no valid position — try a different action

            do_index = random.choice(allowed_do)
            current_action_list.insert(do_index, current_do)

            # --- UNDO scan: find valid positions for the recovery ---
            # Flags are NOT reset here; they carry the state accumulated by
            # the DO scan (reflecting items 0..len-1 of the original list).
            # The UNDO scan updates flags first, then checks — matching Tcl.
            allowed_undo: List[int] = []
            for y in range(do_index + 1, len(current_action_list)):
                item_action, item_targets, _ = _parse_item(
                    current_action_list[y]
                )
                _undo_scan_update_flags(item_action, item_targets, flags)
                if _undo_allowed(
                    current_undo_action, current_do_action,
                    current_do_targets, flags,
                ):
                    allowed_undo.append(y)

            if current_undo_action:
                undo_item = (
                    f"{current_undo_action}"
                    f":{'-'.join(current_do_targets)}"
                    f":{current_do_value}"
                )
                undo_index = (
                    random.choice(allowed_undo)
                    if allowed_undo
                    else do_index + 1  # fallback: insert right after DO
                )
                current_action_list.insert(undo_index, undo_item)

        # Append the group to action_list with random sleeps and a check.
        for element in current_action_list:
            # Tcl: MIN_SLEEP + int((MAX_SLEEP - MIN_SLEEP) * rand())
            sleep_val = min_sleep + int((max_sleep - min_sleep) * random.random())
            action_list.append(element)
            action_list.append(f"sleep::{sleep_val}")
        list_of_actions_number += 1
        action_list.append(f"check::{list_of_actions_number}")

    return action_list


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--subset", "--chaotic-subset",
        default="all",
        metavar="LIST",
        help="Comma-separated action names or 'all' (default: all)",
    )
    parser.add_argument(
        "--max-before-check", type=int, default=30, metavar="N",
        help="Max actions per group before check point (default: 30)",
    )
    parser.add_argument(
        "--max-total", type=int, default=200, metavar="N",
        help="Stop after this many total list items (default: 200)",
    )
    parser.add_argument(
        "--min-sleep", type=int, default=15, metavar="S",
        help="Minimum sleep seconds between actions (default: 15)",
    )
    parser.add_argument(
        "--max-sleep", type=int, default=30, metavar="S",
        help="Maximum sleep seconds between actions (default: 30)",
    )
    parser.add_argument(
        "--external-disk-ip", default="", metavar="IP",
        help="External disk IP; enables externalDiskLinkDown/LinkNetemAdd",
    )
    parser.add_argument(
        "--pubsub-permanent-netem", action="store_true",
        help="Suppress pubsubLinkNetemAdd (permanent netem already applied)",
    )
    parser.add_argument(
        "--external-disk-permanent-netem", action="store_true",
        help="Suppress externalDiskLinkNetemAdd",
    )
    parser.add_argument(
        "--seed", type=int, default=None, metavar="N",
        help="Random seed for reproducible output",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    subset = (
        "all"
        if args.subset == "all"
        else [s.strip() for s in args.subset.split(",") if s.strip()]
    )

    do_action_list = build_do_action_list(
        subset=subset,
        external_disk_ip=args.external_disk_ip,
        pubsub_permanent_netem=args.pubsub_permanent_netem,
        external_disk_permanent_netem=args.external_disk_permanent_netem,
    )

    if not do_action_list:
        print("ERROR: no actions match the given subset", file=sys.stderr)
        return 2

    result = generate(
        do_action_list=do_action_list,
        max_actions_total=args.max_total,
        max_actions_before_check=args.max_before_check,
        min_sleep=args.min_sleep,
        max_sleep=args.max_sleep,
    )

    print(",".join(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
