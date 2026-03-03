#!/usr/bin/env python3
"""
validate_action_list.py — check a chaotic-mode action list from
reg_vmrRedundancyRandomActions.tcl against all constraint rules.

Usage:
    ./validate_action_list.py [file]   # read comma-separated list from file
    ./validate_action_list.py -        # read from stdin
    echo "..." | ./validate_action_list.py

The input is the comma-separated list produced by:
    runAutomation ... -script regScripts/reg_vmrRedundancyRandomActions.tcl \\
        -scriptArgs "-randomize chaotic -generateActionListOnly 1"

Exit codes:
    0   all checks passed
    1   one or more violations found
    2   usage / parse error
"""

import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# UNDO map — matches the Tcl script's UNDO array exactly
# ---------------------------------------------------------------------------
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
    # TLS HA actions
    "mateLinkSslDisable":            "mateLinkSslEnable",
    "configSyncSslDisable":          "configSyncSslEnable",
    "redundancyPskChange":           "redundancyPskAdd",
    "redundancyPskRemove":           "redundancyPskAdd",
    "redundancyGroupPasswordChange": "redundancyGroupPasswordAdd",
    "redundancyGroupPasswordRemove": "redundancyGroupPasswordAdd",
}

# Reverse map: recovery action -> set of do-actions it clears
CLEARED_BY: Dict[str, Set[str]] = defaultdict(set)
for _do, _rec in UNDO.items():
    if _rec:
        CLEARED_BY[_rec].add(_do)

# Actions that set nodeIsolationFlag on their declared targets.
# Note: the Tcl DO-scan uses allTargetsList for these, but the UNDO-scan
# uses per-target; we use per-target here for a conservative check.
NODE_ISOLATION_SETTERS: Set[str] = {
    "isolateNode",
    "messageSpoolDisable",
    "redundancyDisable",
    "messageBackboneServiceDisable",
    "redundancyServiceDisable",
    "linkDown",
    "mateLinkServiceDisable",
    "mateLinkDown",
}

NODE_ISOLATION_CLEARERS: Set[str] = {
    "recoverNode",
    "messageSpoolEnable",
    "redundancyEnable",
    "messageBackboneServiceEnable",
    "redundancyServiceEnable",
    "linkUp",
    "mateLinkServiceEnable",
    "mateLinkUp",
}

# Recovery-only actions: applying these directly is never a precondition
# violation in the "generic" check.
RECOVERY_ACTIONS: Set[str] = set(UNDO.values()) - {""}

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_item(raw: str) -> Tuple[str, List[str], str]:
    """Return (action, targets_list, value) from 'action:targets:value'."""
    parts = raw.split(":")
    action = parts[0] if parts else ""
    targets_str = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""
    targets = [t for t in targets_str.split("-") if t]
    return action, targets, value


def parse_list(text: str) -> List[str]:
    """Split comma-separated text into non-empty raw item strings."""
    return [item.strip() for item in text.split(",") if item.strip()]


def split_into_groups(items: List[str]) -> List[List[str]]:
    """
    Split item list into sub-groups, each ending with a 'check' entry.
    Items after the last check form a final (possibly incomplete) group.
    """
    groups: List[List[str]] = []
    current: List[str] = []
    for raw in items:
        action, _, _ = parse_item(raw)
        current.append(raw)
        if action.startswith("check"):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class State:
    """Per-target runtime flags, mirroring the Tcl script state variables."""

    def __init__(self) -> None:
        self.power_down:      Dict[str, bool] = defaultdict(bool)
        self.ungraceful_down: Dict[str, bool] = defaultdict(bool)
        self.node_isolated:   Dict[str, bool] = defaultdict(bool)
        self.disk_down:       Dict[str, bool] = defaultdict(bool)
        # active_do[target] = set of do-actions applied but not yet recovered
        self.active_do:       Dict[str, Set[str]] = defaultdict(set)

    def apply(self, action: str, targets: List[str]) -> None:
        """Update state flags after applying action to targets."""
        if action == "powerDown":
            for t in targets:
                self.power_down[t] = True
                self.active_do[t].add(action)
        elif action == "powerUp":
            for t in targets:
                self.power_down[t] = False
                self.active_do[t].discard("powerDown")
        elif action == "ungracefulPowerDown":
            for t in targets:
                self.ungraceful_down[t] = True
                self.active_do[t].add(action)
        elif action == "ungracefulPowerUp":
            for t in targets:
                self.ungraceful_down[t] = False
                self.active_do[t].discard("ungracefulPowerDown")
        elif action in NODE_ISOLATION_SETTERS:
            for t in targets:
                self.node_isolated[t] = True
                self.active_do[t].add(action)
        elif action in NODE_ISOLATION_CLEARERS:
            for t in targets:
                self.node_isolated[t] = False
                for do_action in CLEARED_BY.get(action, set()):
                    self.active_do[t].discard(do_action)
        elif action == "externalDiskLinkDown":
            for t in targets:
                self.disk_down[t] = True
                self.active_do[t].add(action)
        elif action == "externalDiskLinkUp":
            for t in targets:
                self.disk_down[t] = False
                self.active_do[t].discard("externalDiskLinkDown")
        else:
            undo = UNDO.get(action, "")
            if undo:
                for t in targets:
                    self.active_do[t].add(action)
            for do_action in CLEARED_BY.get(action, set()):
                for t in targets:
                    self.active_do[t].discard(do_action)


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------

def check_preconditions(
    action: str,
    targets: List[str],
    state: State,
    loc: str,
) -> List[str]:
    """
    Check all constraint rules for this action against the current state.
    Returns a list of violation strings (empty list means no violation).
    """
    violations: List[str] = []

    # Rule 1: General repeat prevention.
    # Any action with a recovery must not be applied to the same target
    # again before that recovery has appeared (SOL-147233).
    undo = UNDO.get(action, "")
    if undo:
        for t in targets:
            if action in state.active_do[t]:
                violations.append(
                    f"{loc}: '{action}' on '{t}' applied again "
                    f"before recovery '{undo}'"
                )

    # Rule 2: Per-action preconditions based on current state flags.
    if action in ("powerDown", "ungracefulPowerDown"):
        for t in targets:
            if state.power_down[t]:
                violations.append(
                    f"{loc}: target '{t}' already powered down"
                )
            if state.ungraceful_down[t]:
                violations.append(
                    f"{loc}: target '{t}' already ungracefully powered down"
                )
    elif action == "reload":
        for t in targets:
            if state.power_down[t]:
                violations.append(
                    f"{loc}: target '{t}' powered down — cannot reload"
                )
            if state.ungraceful_down[t]:
                violations.append(
                    f"{loc}: target '{t}' ungracefully down — cannot reload"
                )
            if state.disk_down[t]:
                violations.append(
                    f"{loc}: target '{t}' has no disk — cannot reload"
                )
    elif action == "externalDiskLinkDown":
        for t in targets:
            if state.disk_down[t]:
                violations.append(f"{loc}: target '{t}' disk already down")
    elif action not in RECOVERY_ACTIONS and action not in ("sleep", "check", ""):
        # Generic: cannot act on a powered-down or isolated target.
        for t in targets:
            if state.power_down[t]:
                violations.append(f"{loc}: target '{t}' is powered down")
            if state.ungraceful_down[t]:
                violations.append(
                    f"{loc}: target '{t}' is ungracefully powered down"
                )
            if state.node_isolated[t]:
                violations.append(f"{loc}: target '{t}' is isolated")

    return violations


def check_end_of_group(state: State, group_num: int) -> List[str]:
    """
    At a check point all disruptions must have been recovered, because the
    check verifies full cluster health.  Returns violation strings.
    """
    violations: List[str] = []
    loc = f"[group {group_num}, end-of-group]"

    for t, is_down in state.power_down.items():
        if is_down:
            violations.append(f"{loc}: target '{t}' still powered down")
    for t, is_down in state.ungraceful_down.items():
        if is_down:
            violations.append(
                f"{loc}: target '{t}' still ungracefully powered down"
            )
    for t, is_isolated in state.node_isolated.items():
        if is_isolated:
            violations.append(f"{loc}: target '{t}' still isolated")
    for t, is_down in state.disk_down.items():
        if is_down:
            violations.append(f"{loc}: target '{t}' disk still down")

    return violations


def validate_group(raw_items: List[str], group_num: int) -> List[str]:
    """Validate one sub-group. Returns all violation strings found."""
    state = State()
    violations: List[str] = []

    for item_num, raw in enumerate(raw_items, start=1):
        action, targets, _ = parse_item(raw)
        if action.startswith(("sleep", "check")) or not action:
            continue

        loc = f"[group {group_num}, item {item_num}] {raw!r}"
        violations.extend(check_preconditions(action, targets, state, loc))

        # Always apply (even on violation) so we surface all issues.
        state.apply(action, targets)

    violations.extend(check_end_of_group(state, group_num))
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def is_action(raw: str) -> bool:
    action, _, _ = parse_item(raw)
    return bool(action) and not action.startswith(("sleep", "check"))


def main() -> int:
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if args and args[0] != "-":
        try:
            with open(args[0]) as f:
                text = f.read()
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()

    items = parse_list(text)
    if not items:
        print("ERROR: empty action list", file=sys.stderr)
        return 2

    groups = split_into_groups(items)
    n_actions = sum(1 for r in items if is_action(r))
    print(
        f"Parsed {len(items)} items "
        f"({n_actions} actions, "
        f"{len(items) - n_actions} sleeps/checks) "
        f"in {len(groups)} group(s)."
    )

    all_violations: List[str] = []
    for group_num, group_items in enumerate(groups, start=1):
        n = sum(1 for r in group_items if is_action(r))
        group_violations = validate_group(group_items, group_num)
        status = f"FAIL ({len(group_violations)} violation(s))" \
            if group_violations else "ok"
        print(f"  Group {group_num}: {n} actions — {status}")
        all_violations.extend(group_violations)

    print()
    if all_violations:
        print(f"FAIL — {len(all_violations)} violation(s):")
        for v in all_violations:
            print(f"  {v}")
        return 1

    print("PASS — no violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
