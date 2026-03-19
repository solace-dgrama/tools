# rerun_afw_test.py

Re-run an AFW test with different brokers and/or performance hosts.

## Usage

```
rerun_afw_test.py URL [--dry-run]
```

`URL` is the AFW summary page for the test run you want to reproduce, e.g.:

```
rerun_afw_test.py http://192.168.2.88/sustaining/summary.php?ChildID=22351341
```

`--dry-run` prints the new commands without executing them.

## What it does

1. Fetches the AFW summary page and extracts:
   - `Setup` field → `sting-vmr` command (may be absent)
   - `Test Script Command Line` / `Command Line` field → `runAutomation` command
   - `Load` field → broker load version
   - `PerfHosts` section → original perf-host OS types

2. Displays the **original resources** (brokers with type info, load version, perf hosts).

3. Displays your **currently booked bookit resources** and offers to auto-book
   replacements matching the original resource types.

4. If you decline auto-booking, prompts you to enter new broker and perf-host
   names manually.

5. Prompts for the **broker load version** (with fuzzy matching against
   `/home/public/RND/loads/solcbr`).

6. Prompts for a **local scripts directory** (`SOL_AFW_CURRENT_LIB`), rewrites
   the `-script` path to be relative, and sources the AFW environment.

7. Shows warnings for:
   - Resource count mismatches vs. the original
   - Resources not booked by you (ownership check via bookit)
   - Resource type mismatches vs. the original

8. Prints the new `sting-vmr` and `runAutomation` commands, then offers to
   run them.

## Interactive flow

```
Fetching <URL> ...
[WARNING if no Setup field]

--- Original resources ---
  Brokers (looking up types): ...
  Version    : ...
  Perf hosts : ...

  Your current bookit resources:
    <name> - <type desc> [<end time>]
    ...

Auto-book resources via bookit? [y/N]
```

**If auto-booking (`y`):**
- Asks for booking duration (default 4 h) and message (default `afw troubleshooting`)
- Looks up original resource types, builds matching bookit queries
- Books brokers and perf hosts; falls back to any available if no match
- Prompts for monitoring nodes from the new broker list (if sting-vmr present)

**If manual (`N`):**
- Prompts for new broker names (space/comma separated)
- Prompts for monitoring nodes (if sting-vmr present)
- Prompts for new perf host names or IPs

**Both paths continue with:**
- Load version prompt (with fuzzy match / candidate list)
- Local scripts directory prompt
- Ownership and type-compatibility warnings
- Run selection menu

## Perf-host naming

Perf hosts follow the convention `perf-A-B` ↔ `192.168.A.B`. Either form is
accepted at all prompts; the script normalises internally to IPs and displays
both forms.

## Load version matching

Loads are looked up under `/home/public/RND/loads/solcbr` in three layouts:

| Type    | Path layout                              | Example version        |
|---------|------------------------------------------|------------------------|
| Regular | `<X.Y.Z>/<X.Y.Z.BUILD>/`                | `10.25.0.202`          |
| Main    | `main/<VERSION>/`                        | `100.0main.0.5554`     |
| Feature | `feature/<NAME>/<VERSION>/`              | `100.0SOL-144552.0.5612` |

Partial strings are accepted; the script searches for directory names that
contain the input and presents matching candidates.

## Bookit integration

The script uses the `bookit` CLI (must be on `PATH`). Key operations:

- `bookit --status-json` — list your current bookings
- `bookit --type <type> --book --queue <query> ...` — attempt to book one resource
- `bookit --type <type> --free <name>` — release a resource

Resource types used: `vmr`, `appliance`, `perf-host`.

Booking queries are built from the original resource attributes:
- VMR: `num_cpus:<N> ram:<X>`
- Appliance: `platform:<P> sub_platform:<S>`
- Perf host: `OS:<OS> OS_version:<VER>`

If a query yields nothing, the script retries with `*` (any available).

## No Setup field

When the `Setup` field is absent from the AFW page (no `sting-vmr` command),
the script continues with `runAutomation` only. Your current bookit resources
are still displayed, auto-booking is still offered (broker list comes from the
`-hosts` field of the `runAutomation` command), and monitoring-node prompts
are skipped.

## Dependencies

- Python 3.10+
- `bookit` CLI on `PATH` (available at
  `/opt/sbox/dgrama/devenv/devtools/efunnekotter/servers/bookit/`)
- Network access to the AFW summary page host
- `/home/public/RND/loads/solcbr` mounted (for load availability checks)
