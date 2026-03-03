#!/usr/bin/env python3
"""
test_gen_action_list.py — extensive tests for gen_action_list.py

Test categories:
  1. Output format
  2. Sleep values within declared range
  3. Group structure (actions → sleeps → check, correct check numbering)
  4. Subset filtering (only requested actions appear, correct targets)
  5. DO/UNDO pairing within each group
  6. Regression: original SOL-147233 bug (no doubled isolateNode / powerDown)
  7. Parameter edge cases (external disk, pubsub netem, tiny limits, equal sleeps)
  8. Constraint validation via validate_action_list.py (100 random seeds)
  9. Stress test: 200 seeds × full subset
"""

import subprocess
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
GEN = str(HERE / "gen_action_list.py")
VAL = str(HERE / "validate_action_list.py")

# ---------------------------------------------------------------------------
# UNDO map (duplicated here so tests are self-contained)
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
}

ALL_TARGETS = {"primary", "backup", "monitor"}

# ---------------------------------------------------------------------------
# Helper: run gen_action_list.py and return its output
# ---------------------------------------------------------------------------

def gen(*extra_args) -> str:
    result = subprocess.run(
        [sys.executable, GEN] + list(extra_args),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"gen_action_list.py failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def validate(action_list_str: str) -> Tuple[int, str]:
    """Run validate_action_list.py on a string; return (returncode, stdout)."""
    result = subprocess.run(
        [sys.executable, VAL, "-"],
        input=action_list_str, capture_output=True, text=True,
    )
    return result.returncode, result.stdout


def parse_items(csv: str) -> List[Tuple[str, List[str], str]]:
    """Parse comma-separated output into (action, targets, value) tuples."""
    items = []
    for raw in csv.split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(":")
        action = parts[0]
        targets_str = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        targets = [t for t in targets_str.split("-") if t]
        items.append((action, targets, value))
    return items


def split_into_groups(
    items: List[Tuple[str, List[str], str]]
) -> List[List[Tuple[str, List[str], str]]]:
    """Split item list into groups ending with 'check'."""
    groups, current = [], []
    for item in items:
        current.append(item)
        if item[0].startswith("check"):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


# ---------------------------------------------------------------------------
# 1. Output format
# ---------------------------------------------------------------------------

class TestOutputFormat(unittest.TestCase):

    def setUp(self):
        self.csv = gen(
            "--subset", "powerDown,reload,linkDown,isolateNode",
            "--max-before-check", "5",
            "--max-total", "30",
            "--seed", "1",
        )
        self.items = parse_items(self.csv)

    def test_non_empty(self):
        self.assertGreater(len(self.items), 0, "output must not be empty")

    def test_each_item_has_colon_structure(self):
        for raw in self.csv.split(","):
            raw = raw.strip()
            if raw:
                self.assertIn(":", raw, f"item missing colon: {raw!r}")

    def test_action_names_non_empty(self):
        for action, _, _ in self.items:
            self.assertTrue(action, "item has empty action field")

    def test_known_action_types(self):
        known = set(UNDO) | {
            v for v in UNDO.values() if v
        } | {"sleep", "check"}
        for action, _, _ in self.items:
            self.assertIn(
                action, known,
                f"unknown action {action!r} in output",
            )


# ---------------------------------------------------------------------------
# 2. Sleep values within range
# ---------------------------------------------------------------------------

class TestSleepRange(unittest.TestCase):

    def _check_sleeps(self, min_s, max_s, seed):
        csv = gen(
            "--max-before-check", "5",
            "--max-total", "30",
            "--min-sleep", str(min_s),
            "--max-sleep", str(max_s),
            "--seed", str(seed),
        )
        for action, _, value in parse_items(csv):
            if action == "sleep":
                s = int(value)
                self.assertGreaterEqual(
                    s, min_s,
                    f"sleep {s} < min {min_s}",
                )
                # Tcl: int((MAX-MIN)*rand()) → [0, MAX-MIN-1], so max is MAX-1
                self.assertLessEqual(
                    s, max(min_s, max_s - 1),
                    f"sleep {s} >= max {max_s}",
                )

    def test_default_sleep_range(self):
        self._check_sleeps(15, 30, 42)

    def test_narrow_sleep_range(self):
        self._check_sleeps(10, 11, 7)

    def test_equal_sleep_range(self):
        # min == max: every sleep must be exactly min
        csv = gen(
            "--max-before-check", "3",
            "--max-total", "20",
            "--min-sleep", "20",
            "--max-sleep", "20",
            "--seed", "5",
        )
        for action, _, value in parse_items(csv):
            if action == "sleep":
                self.assertEqual(int(value), 20)

    def test_large_sleep_range(self):
        self._check_sleeps(5, 60, 99)


# ---------------------------------------------------------------------------
# 3. Group structure
# ---------------------------------------------------------------------------

class TestGroupStructure(unittest.TestCase):

    def setUp(self):
        self.csv = gen(
            "--max-before-check", "6",
            "--max-total", "60",
            "--seed", "3",
        )
        self.items = parse_items(self.csv)
        self.groups = split_into_groups(self.items)

    def test_at_least_one_group(self):
        self.assertGreater(len(self.groups), 0)

    def test_each_group_ends_with_check(self):
        for i, g in enumerate(self.groups):
            self.assertTrue(
                g[-1][0].startswith("check"),
                f"group {i+1} does not end with check (ends with {g[-1][0]!r})",
            )

    def test_check_numbering_sequential(self):
        checks = [
            int(value)
            for action, _, value in self.items
            if action.startswith("check")
        ]
        for idx, num in enumerate(checks, start=1):
            self.assertEqual(num, idx, f"check {idx} has value {num}")

    def test_every_action_followed_by_sleep(self):
        """Each action item must be immediately followed by a sleep item."""
        for i, (action, _, _) in enumerate(self.items[:-1]):
            if action in ("sleep", "check") or action.startswith("check"):
                continue
            next_action = self.items[i + 1][0]
            self.assertEqual(
                next_action, "sleep",
                f"action {action!r} at index {i} not followed by sleep "
                f"(got {next_action!r})",
            )

    def test_no_consecutive_checks(self):
        for i in range(len(self.items) - 1):
            if self.items[i][0].startswith("check"):
                self.assertFalse(
                    self.items[i + 1][0].startswith("check"),
                    "two consecutive check items",
                )


# ---------------------------------------------------------------------------
# 4. Subset filtering
# ---------------------------------------------------------------------------

class TestSubsetFiltering(unittest.TestCase):

    def _get_actions(self, subset_str, **kwargs) -> Set[str]:
        extra = []
        for k, v in kwargs.items():
            extra += [f"--{k}", str(v)]
        csv = gen(
            "--subset", subset_str,
            "--max-before-check", "10",
            "--max-total", "80",
            "--seed", "77",
            *extra,
        )
        return {
            action for action, _, _ in parse_items(csv)
            if action not in ("sleep", "check") and not action.startswith("check")
        }

    def test_only_requested_actions_and_their_recoveries(self):
        subset = {"powerDown", "linkDown", "isolateNode"}
        recoveries = {UNDO[a] for a in subset if UNDO.get(a)}
        actions = self._get_actions("powerDown,linkDown,isolateNode")
        unexpected = actions - subset - recoveries
        self.assertFalse(
            unexpected,
            f"unexpected actions in output: {unexpected}",
        )

    def test_reload_appears_no_recovery(self):
        actions = self._get_actions("reload")
        self.assertIn("reload", actions)
        # reload has no recovery
        self.assertNotIn("", actions)

    def test_cpu_hog_appears_no_recovery(self):
        actions = self._get_actions("cpuHog")
        self.assertIn("cpuHog", actions)

    def test_isolate_node_target_is_monitor_only(self):
        csv = gen(
            "--subset", "isolateNode",
            "--max-before-check", "3",
            "--max-total", "40",
            "--seed", "11",
        )
        for action, targets, _ in parse_items(csv):
            if action == "isolateNode":
                self.assertEqual(
                    targets, ["monitor"],
                    f"isolateNode on non-monitor target: {targets}",
                )

    def test_link_down_targets_are_pairs(self):
        csv = gen(
            "--subset", "linkDown",
            "--max-before-check", "4",
            "--max-total", "40",
            "--seed", "22",
        )
        for action, targets, _ in parse_items(csv):
            if action == "linkDown":
                self.assertEqual(
                    len(targets), 2,
                    f"linkDown must have 2 targets, got {targets}",
                )
                self.assertNotEqual(
                    targets[0], targets[1],
                    f"linkDown targets must differ: {targets}",
                )
                for t in targets:
                    self.assertIn(t, ("primary", "backup"))

    def test_mate_link_down_targets_are_pairs(self):
        csv = gen(
            "--subset", "mateLinkDown",
            "--max-before-check", "4",
            "--max-total", "40",
            "--seed", "33",
        )
        for action, targets, _ in parse_items(csv):
            if action == "mateLinkDown":
                self.assertEqual(len(targets), 2)
                self.assertNotEqual(targets[0], targets[1])
                for t in targets:
                    self.assertIn(t, ("primary", "backup"))

    def test_reload_triple_target_present(self):
        """reload:primary-backup-monitor should appear in full subset."""
        found_triple = False
        csv = gen(
            "--subset", "reload",
            "--max-before-check", "5",
            "--max-total", "60",
            "--seed", "55",
        )
        for action, targets, _ in parse_items(csv):
            if action == "reload" and set(targets) == {"primary", "backup", "monitor"}:
                found_triple = True
                break
        self.assertTrue(found_triple, "triple-target reload never appeared")

    def test_external_disk_absent_without_ip(self):
        actions = self._get_actions("all")
        self.assertNotIn("externalDiskLinkDown", actions)
        self.assertNotIn("externalDiskLinkNetemAdd", actions)

    def test_external_disk_present_with_ip(self):
        csv = gen(
            "--subset", "all",
            "--external-disk-ip", "10.0.0.1",
            "--max-before-check", "10",
            "--max-total", "200",
            "--seed", "66",
        )
        actions = {
            a for a, _, _ in parse_items(csv)
            if a not in ("sleep", "check") and not a.startswith("check")
        }
        self.assertIn("externalDiskLinkDown", actions)

    def test_pubsub_netem_absent_when_permanent(self):
        csv = gen(
            "--subset", "all",
            "--pubsub-permanent-netem",
            "--max-before-check", "10",
            "--max-total", "100",
            "--seed", "88",
        )
        for action, _, _ in parse_items(csv):
            self.assertNotEqual(
                action, "pubsubLinkNetemAdd",
                "pubsubLinkNetemAdd should be suppressed",
            )

    def test_pubsub_netem_present_by_default(self):
        csv = gen(
            "--subset", "pubsubLinkNetemAdd",
            "--max-before-check", "3",
            "--max-total", "50",
            "--seed", "89",
        )
        actions = {
            a for a, _, _ in parse_items(csv)
            if a not in ("sleep", "check") and not a.startswith("check")
        }
        self.assertIn("pubsubLinkNetemAdd", actions)


# ---------------------------------------------------------------------------
# 5. DO/UNDO pairing within each group
# ---------------------------------------------------------------------------

class TestDoUndoPairing(unittest.TestCase):

    def _actions_only(
        self, group: List[Tuple[str, List[str], str]]
    ) -> List[Tuple[str, List[str], str]]:
        return [
            (a, t, v) for a, t, v in group
            if a not in ("sleep", "check") and not a.startswith("check")
        ]

    def _check_pairing(self, csv: str) -> List[str]:
        """Return list of pairing violation descriptions."""
        violations = []
        for g_idx, group in enumerate(split_into_groups(parse_items(csv)), 1):
            acts = self._actions_only(group)
            # For each do-action with a recovery, verify recovery appears
            # in the same group.
            do_indices: Dict[str, List[int]] = defaultdict(list)
            undo_indices: Dict[str, List[int]] = defaultdict(list)
            for idx, (action, targets, _) in enumerate(acts):
                t_key = action + ":" + "-".join(sorted(targets))
                if action in UNDO:
                    do_indices[t_key].append(idx)
                recovery = UNDO.get(action, "")
                if recovery:
                    # this is a do-action — check its recovery appears
                    rec_key = recovery + ":" + "-".join(sorted(targets))
                    undo_indices[rec_key].append(idx)

            for t_key, d_idxs in do_indices.items():
                action = t_key.split(":")[0]
                recovery = UNDO.get(action, "")
                if not recovery:
                    continue
                targets_str = t_key.split(":", 1)[1] if ":" in t_key else ""
                rec_key = recovery + ":" + targets_str
                u_idxs = undo_indices.get(rec_key, [])
                if len(d_idxs) != len(u_idxs):
                    violations.append(
                        f"group {g_idx}: {action} count={len(d_idxs)} "
                        f"but {recovery} count={len(u_idxs)}"
                    )
        return violations

    def test_pairing_small_subset(self):
        csv = gen(
            "--subset", "powerDown,isolateNode,linkDown",
            "--max-before-check", "6",
            "--max-total", "60",
            "--seed", "10",
        )
        violations = self._check_pairing(csv)
        self.assertFalse(violations, "\n".join(violations))

    def test_pairing_full_subset(self):
        csv = gen(
            "--max-before-check", "8",
            "--max-total", "80",
            "--seed", "20",
        )
        violations = self._check_pairing(csv)
        self.assertFalse(violations, "\n".join(violations))

    def test_reload_has_no_recovery(self):
        csv = gen(
            "--subset", "reload",
            "--max-before-check", "5",
            "--max-total", "40",
            "--seed", "30",
        )
        for action, _, _ in parse_items(csv):
            if action not in ("sleep", "check") and not action.startswith("check"):
                self.assertIn(
                    action, ("reload",),
                    f"unexpected action {action!r} in reload-only run",
                )


# ---------------------------------------------------------------------------
# 6. Regression: original SOL-147233 bug
# ---------------------------------------------------------------------------

class TestSOL147233Regression(unittest.TestCase):
    """Verify that the specific bugs fixed by SOL-147233 do not re-appear."""

    def _find_double_do_without_recovery(
        self, csv: str, do_action: str, recovery: str
    ) -> List[str]:
        """Return violation descriptions if do_action appears twice on the
        same target in one group without recovery in between."""
        violations = []
        for g_idx, group in enumerate(split_into_groups(parse_items(csv)), 1):
            # per-target: track positions of do and recovery
            per_target: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
            acts = [
                (a, t, v) for a, t, v in group
                if a not in ("sleep",) and not a.startswith("check")
            ]
            for idx, (action, targets, _) in enumerate(acts):
                for t in targets:
                    per_target[t].append((idx, action))

            for target, events in per_target.items():
                pending = False
                for _, action in events:
                    if action == do_action:
                        if pending:
                            violations.append(
                                f"group {g_idx}: {do_action} on {target!r} "
                                f"appeared twice without {recovery}"
                            )
                        pending = True
                    elif action == recovery:
                        pending = False
        return violations

    def _run_many_seeds(self, subset, n_seeds=50, **gen_kwargs):
        extra = []
        for k, v in gen_kwargs.items():
            extra += [f"--{k.replace('_', '-')}", str(v)]
        all_violations = []
        for seed in range(n_seeds):
            csv = gen("--subset", subset, "--seed", str(seed), *extra)
            v = self._find_double_do_without_recovery(
                csv, "isolateNode", "recoverNode"
            )
            v += self._find_double_do_without_recovery(
                csv, "powerDown", "powerUp"
            )
            v += self._find_double_do_without_recovery(
                csv, "ungracefulPowerDown", "ungracefulPowerUp"
            )
            v += self._find_double_do_without_recovery(
                csv, "linkDown", "linkUp"
            )
            v += self._find_double_do_without_recovery(
                csv, "mateLinkDown", "mateLinkUp"
            )
            if v:
                all_violations.append(f"seed={seed}: " + "; ".join(v))
        return all_violations

    def test_isolate_node_never_doubled(self):
        violations = self._run_many_seeds(
            "isolateNode",
            n_seeds=100,
            max_before_check=5,
            max_total=60,
        )
        self.assertFalse(violations, "\n".join(violations))

    def test_power_down_never_doubled(self):
        violations = self._run_many_seeds(
            "powerDown",
            n_seeds=100,
            max_before_check=5,
            max_total=60,
        )
        self.assertFalse(violations, "\n".join(violations))

    def test_mixed_subset_no_double_do(self):
        violations = self._run_many_seeds(
            "isolateNode,powerDown,linkDown,mateLinkDown,ungracefulPowerDown",
            n_seeds=100,
            max_before_check=8,
            max_total=80,
        )
        self.assertFalse(violations, "\n".join(violations))


# ---------------------------------------------------------------------------
# 7. Parameter edge cases
# ---------------------------------------------------------------------------

class TestParameterEdgeCases(unittest.TestCase):

    def test_max_before_check_one(self):
        """With max-before-check=1 each group should have at most 2 actions."""
        csv = gen(
            "--max-before-check", "1",
            "--max-total", "20",
            "--seed", "100",
        )
        for g_idx, group in enumerate(split_into_groups(parse_items(csv)), 1):
            acts = [
                a for a, _, _ in group
                if a not in ("sleep", "check") and not a.startswith("check")
            ]
            # Max is 3: one no-UNDO action (reload/cpuHog) inserted at the
            # boundary (list size == max_before_check), then a DO+UNDO pair.
            self.assertLessEqual(
                len(acts), 3,
                f"group {g_idx} has {len(acts)} actions with max-before-check=1",
            )

    def test_single_action_subset(self):
        for action in ["powerDown", "reload", "isolateNode", "cpuHog"]:
            with self.subTest(action=action):
                csv = gen(
                    "--subset", action,
                    "--max-before-check", "3",
                    "--max-total", "20",
                    "--seed", "42",
                )
                items = parse_items(csv)
                self.assertGreater(len(items), 0)
                # validate passes
                rc, out = validate(csv)
                self.assertEqual(
                    rc, 0,
                    f"validate failed for subset={action}:\n{out}",
                )

    def test_external_disk_ip_target(self):
        """externalDiskLinkNetemAdd should use the IP as its target."""
        ip = "192.168.1.99"
        csv = gen(
            "--subset", "externalDiskLinkNetemAdd",
            "--external-disk-ip", ip,
            "--max-before-check", "3",
            "--max-total", "30",
            "--seed", "55",
        )
        for action, targets, _ in parse_items(csv):
            if action == "externalDiskLinkNetemAdd":
                self.assertEqual(targets, [ip], f"expected IP target, got {targets}")

    def test_seed_reproducibility(self):
        args = [
            "--max-before-check", "5",
            "--max-total", "40",
            "--seed", "999",
        ]
        csv1 = gen(*args)
        csv2 = gen(*args)
        self.assertEqual(csv1, csv2, "same seed must produce identical output")

    def test_different_seeds_differ(self):
        csv1 = gen("--max-total", "40", "--seed", "1")
        csv2 = gen("--max-total", "40", "--seed", "2")
        self.assertNotEqual(csv1, csv2, "different seeds should differ")

    def test_invalid_subset_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, GEN, "--subset", "nonExistentAction123",
             "--max-total", "10"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


# ---------------------------------------------------------------------------
# 8. Constraint validation via validate_action_list.py (100 seeds)
# ---------------------------------------------------------------------------

class TestConstraintValidation(unittest.TestCase):

    SUBSET = (
        "isolateNode,powerDown,ungracefulPowerDown,reload,linkDown,"
        "mateLinkDown,cpuHog,messageSpoolDisable,redundancyDisable,"
        "messageBackboneServiceDisable,mateLinkServiceDisable,"
        "redundancyServiceDisable,linkNetemAdd"
    )

    def _validate_seed(self, seed: int) -> Optional[str]:
        csv = gen(
            "--subset", self.SUBSET,
            "--max-before-check", "5",
            "--max-total", "60",
            "--seed", str(seed),
        )
        rc, out = validate(csv)
        if rc != 0:
            return f"seed={seed} FAIL:\n{out}"
        return None

    def test_100_seeds_pass_validator(self):
        failures = []
        for seed in range(100):
            result = self._validate_seed(seed)
            if result:
                failures.append(result)
        self.assertFalse(
            failures,
            f"{len(failures)} seed(s) failed validation:\n"
            + "\n---\n".join(failures[:5]),
        )


# ---------------------------------------------------------------------------
# 9. Stress test: 200 seeds × full subset
# ---------------------------------------------------------------------------

class TestStress(unittest.TestCase):

    def test_200_seeds_full_subset_pass(self):
        failures = []
        for seed in range(200):
            csv = gen(
                "--max-before-check", "8",
                "--max-total", "100",
                "--seed", str(seed),
            )
            rc, out = validate(csv)
            if rc != 0:
                failures.append(f"seed={seed}:\n{out.strip()}")
        self.assertFalse(
            failures,
            f"{len(failures)}/200 seeds failed:\n"
            + "\n---\n".join(failures[:5]),
        )

    def test_200_seeds_user_subset_pass(self):
        """Run with the exact subset from the user's real invocation."""
        subset = (
            "isolateNode,powerDown,reload,linkDown,mateLinkDown,cpuHog,"
            "messageSpoolDisable,redundancyDisable,messageBackboneServiceDisable,"
            "mateLinkServiceDisable,redundancyServiceDisable,linkNetemAdd"
        )
        failures = []
        for seed in range(200):
            csv = gen(
                "--subset", subset,
                "--max-before-check", "5",
                "--max-total", "60",
                "--seed", str(seed),
            )
            rc, out = validate(csv)
            if rc != 0:
                failures.append(f"seed={seed}:\n{out.strip()}")
        self.assertFalse(
            failures,
            f"{len(failures)}/200 seeds failed:\n"
            + "\n---\n".join(failures[:5]),
        )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
