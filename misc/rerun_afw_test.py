#!/usr/bin/env python3
"""Re-run an AFW test with different brokers and/or performance hosts.

Usage
-----
    rerun_afw_test.py URL [--dry-run]

    rerun_afw_test.py --dry-run
        https://internal.soltest.net/summary.php?ChildID=22555730

The URL is the AFW summary page for the test run you want to reproduce.  The
script fetches the page, extracts the afw-tools sting-vmr command and the
runAutomation command, then prompts for new broker and perf-host names.

All sting-vmr options (docker config, scaling, vmr-type, …) are kept as-is.
Only the broker names, monitoring-node list, and perf-host IPs change.
"""

import argparse
import datetime as dt
import html
import json
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Perf-host name/IP helpers  (perf-A-B  ↔  192.168.A.B)
# ---------------------------------------------------------------------------

_PERF_HOST_RE = re.compile(r'^perf-(\d+)-(\d+)$')
_PERF_IP_RE   = re.compile(r'^192\.168\.(\d+)\.(\d+)$')


def perf_host_to_ip(hostname: str) -> str:
    m = _PERF_HOST_RE.match(hostname)
    return f'192.168.{m.group(1)}.{m.group(2)}' if m else hostname


def ip_to_perf_host(ip: str) -> str:
    m = _PERF_IP_RE.match(ip)
    return f'perf-{m.group(1)}-{m.group(2)}' if m else ip


def normalize_to_ip(host_or_ip: str) -> str:
    """Return 192.168.x.y for a perf hostname or IP; pass through unknowns."""
    if _PERF_IP_RE.match(host_or_ip):
        return host_or_ip
    return perf_host_to_ip(host_or_ip)


def display_perf(ip: str) -> str:
    hostname = ip_to_perf_host(ip)
    return f'{ip} ({hostname})' if hostname != ip else ip


# ---------------------------------------------------------------------------
# Fetch commands from the AFW summary page
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def fetch_commands(url: str) -> tuple[str, str]:
    """Return (sting_cmd, run_cmd) extracted from an AFW summary page URL."""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode('utf-8', errors='replace')
    except Exception as exc:
        sys.exit(f'ERROR fetching {url}: {exc}')

    def extract(label: str) -> str | None:
        # Match <b>LABEL</b> : </td><td>CONTENT</td>
        m = re.search(
            rf'<b>{re.escape(label)}</b>\s*:\s*</td><td>(.*?)</td>',
            body, re.DOTALL,
        )
        if not m:
            return None
        return html.unescape(_strip_tags(m.group(1)))

    sting_cmd = extract('Setup')
    # 'Test Script Command Line' has the full -scriptArgs; prefer it over
    # the parent-level 'Command Line' which may use &quot; encoding.
    run_cmd = extract('Test Script Command Line') or extract('Command Line')

    if not sting_cmd:
        sys.exit('ERROR: "Setup" field not found on the page')
    if not run_cmd:
        sys.exit('ERROR: runAutomation command not found on the page')

    return sting_cmd, run_cmd


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def parse_sting_vmr(cmd: str) -> dict:
    """Parse an afw-tools sting-vmr command.

    Returns a dict with:
        pre      - tokens up to and including 'sting-vmr'
        brokers  - list of broker hostnames (positional args)
        version  - load version string (last positional arg)
        monitor  - list of monitoring-node hostnames
        opts     - option tokens that follow the positional args
    """
    tokens = shlex.split(cmd)
    try:
        sv_idx = tokens.index('sting-vmr')
    except ValueError:
        raise ValueError("'sting-vmr' not found in command")

    pre = tokens[:sv_idx + 1]

    positional: list[str] = []
    i = sv_idx + 1
    while i < len(tokens) and not tokens[i].startswith('--'):
        positional.append(tokens[i])
        i += 1

    if len(positional) < 2:
        raise ValueError('Expected at least one broker hostname and a version')

    brokers = positional[:-1]
    version = positional[-1]
    opts = tokens[i:]

    monitor: list[str] = []
    j = 0
    while j < len(opts):
        if opts[j] in ('--monitoring-nodes', '--monitoring-node', '-m'):
            j += 1
            if j < len(opts):
                monitor = [h.strip() for h in opts[j].split(',') if h.strip()]
        j += 1

    return {
        'pre': pre,
        'brokers': brokers,
        'version': version,
        'monitor': monitor,
        'opts': opts,
    }


def parse_run_automation(cmd: str) -> dict:
    """Parse a runAutomation command.

    Returns a dict with:
        hosts     - list of broker hostnames from -hosts
        phosts    - list of perf host IPs from -pHosts
        perf_host - value of -perfHost inside -scriptArgs (may be None)
        tool_ip   - value of -toolIp inside -scriptArgs (may be None)
        raw       - original string used for reconstruction
    """
    hosts_m  = re.search(r'-hosts\s+"?([^"\s]+)"?', cmd)
    phosts_m = re.search(r'-pHosts\s+"?([^"\s]+)"?', cmd)

    hosts  = hosts_m.group(1).split(',')  if hosts_m  else []
    phosts = phosts_m.group(1).split(',') if phosts_m else []

    sa_m = re.search(r'-scriptArgs\s+"([^"]*)"', cmd)
    sa   = sa_m.group(1) if sa_m else ''

    perf_host_m = re.search(r'-perfHost\s+(\S+)', sa)
    tool_ip_m   = re.search(r'-toolIp\s+(\S+)',   sa)

    return {
        'hosts':     hosts,
        'phosts':    phosts,
        'perf_host': perf_host_m.group(1) if perf_host_m else None,
        'tool_ip':   tool_ip_m.group(1)   if tool_ip_m   else None,
        'raw':       cmd,
    }


# ---------------------------------------------------------------------------
# Command reconstruction
# ---------------------------------------------------------------------------

def build_sting_vmr(
    parsed: dict,
    new_brokers: list[str],
    new_monitor: list[str],
    version: str,
) -> str:
    """Return a new sting-vmr command with substituted brokers/monitor/version."""
    new_opts: list[str] = []
    opts = parsed['opts']
    i = 0
    while i < len(opts):
        tok = opts[i]
        if tok in ('--monitoring-nodes', '--monitoring-node', '-m'):
            new_opts.append(tok)
            i += 1
            if i < len(opts):
                new_opts.append(','.join(new_monitor))
                i += 1
        else:
            new_opts.append(tok)
            i += 1

    parts = parsed['pre'] + new_brokers + [version] + new_opts
    return ' '.join(shlex.quote(t) for t in parts)


def build_run_automation(
    parsed: dict,
    new_brokers: list[str],
    new_phosts_ips: list[str],
    new_perf_host_ip: str,
) -> str:
    """Return a new runAutomation command with substituted resources."""
    cmd = parsed['raw']
    new_hosts  = ','.join(new_brokers)
    new_phosts = ','.join(new_phosts_ips)

    cmd = re.sub(r'(-hosts\s+)"?[^"\s]+"?',  f'\\1"{new_hosts}"',  cmd)
    cmd = re.sub(r'(-pHosts\s+)"?[^"\s]+"?', f'\\1"{new_phosts}"', cmd)
    cmd = re.sub(r'(-perfHost\s+)\S+', f'\\g<1>{new_perf_host_ip}', cmd)
    cmd = re.sub(r'(-toolIp\s+)\S+',   f'\\g<1>{new_perf_host_ip}', cmd)

    return cmd


# ---------------------------------------------------------------------------
# Script-path localisation
# ---------------------------------------------------------------------------

def localize_run_automation(cmd: str, scripts_dir: Path) -> str:
    """Rewrite the runAutomation command to run from a local scripts directory.

    Converts the Jenkins absolute -script path to a relative one by taking
    everything after the last '/scripts/' segment, then ensures the command
    itself is invoked as './runAutomation'.
    """
    def rebase(m: re.Match) -> str:
        orig = m.group(2)
        parts = orig.split('/scripts/')
        rel = './' + parts[-1] if len(parts) > 1 else orig
        return m.group(1) + rel

    cmd = re.sub(r'(-script\s+)(\S+)', rebase, cmd)
    cmd = re.sub(r'^\S*runAutomation\b', './runAutomation', cmd)
    return cmd


def get_afw_env(scripts_dir: Path) -> dict[str, str]:
    """Return env vars that are new or changed after the AFW setup sourcing."""
    import os
    e2e_dir = scripts_dir.parent
    bash_cmd = (
        f'export SOL_AFW_CURRENT_LIB={shlex.quote(str(e2e_dir))} && '
        f'source "$SOL_AFW_CURRENT_LIB/envInfo/.bashrc.afw.tcllib" && '
        f'env -0'
    )
    result = subprocess.run(
        ['bash', '-c', bash_cmd], capture_output=True, text=True,
    )
    after = {}
    for entry in result.stdout.split('\0'):
        if '=' in entry:
            k, _, v = entry.partition('=')
            after[k] = v

    return {
        k: v for k, v in after.items()
        if k != '_' and (k not in os.environ or os.environ[k] != v)
    }


def prompt_scripts_dir() -> Path | None:
    """Ask where the local scripts directory is (where runAutomation lives)."""
    default = Path('tests/e2e/scripts')
    hint = f' [{default}]' if default.is_dir() else ''
    raw = input(f'\n  Local scripts directory (where runAutomation lives){hint}: ').strip()
    if not raw and not default.is_dir():
        return None
    chosen = Path(raw) if raw else default
    if not chosen.is_dir():
        print(f'  WARNING: {chosen} does not exist; paths will not be rewritten.')
        return None
    resolved = chosen.resolve()
    afw_env = get_afw_env(resolved)
    if afw_env:
        print('  Environment variables to be set:')
        for k, v in sorted(afw_env.items()):
            print(f'    {k}={v}')
    return resolved


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if x in seen or seen.add(x)]  # type: ignore[func-returns-value]


def prompt_split(label: str, original: list[str]) -> list[str]:
    print(f'\n  Original {label}: {", ".join(original)}')
    while True:
        raw = input(f'  New {label} (space or comma separated): ').strip()
        items = [h for h in re.split(r'[,\s]+', raw) if h]
        dups = _duplicates(items)
        if dups:
            print(f'  ERROR: duplicates: {", ".join(dups)}. Please try again.')
            continue
        if len(items) != len(original):
            print(f'  Warning: got {len(items)} but original had {len(original)}.')
        return items


def prompt_monitor(new_brokers: list[str], original_monitor: list[str]) -> list[str]:
    print(f'\n  Original monitoring nodes : {", ".join(original_monitor) or "(none)"}')
    print(f'  Available new brokers     : {", ".join(new_brokers)}')
    broker_set = set(new_brokers)
    while True:
        raw = input('  Monitoring node(s) (space or comma separated): ').strip()
        nodes = [h for h in re.split(r'[,\s]+', raw) if h]
        dups = _duplicates(nodes)
        if dups:
            print(f'  ERROR: duplicates: {", ".join(dups)}. Please try again.')
            continue
        outside = [n for n in nodes if n not in broker_set]
        if outside:
            print(f'  ERROR: not in broker list: {", ".join(outside)}. Please try again.')
            continue
        return nodes


def prompt_perf_hosts(original_ips: list[str]) -> list[str]:
    display = ', '.join(display_perf(ip) for ip in original_ips)
    print(f'\n  Original perf hosts: {display}')
    while True:
        raw = input('  New perf hosts (hostname or IP, space or comma separated): ').strip()
        items = [normalize_to_ip(h) for h in re.split(r'[,\s]+', raw) if h]
        dups = _duplicates(items)
        if dups:
            print(f'  ERROR: duplicates: {", ".join(display_perf(d) for d in dups)}. Please try again.')
            continue
        return items


# ---------------------------------------------------------------------------
# Resource booking via bookit
# ---------------------------------------------------------------------------

def _bookit_current() -> list[dict]:
    """Return the list of currently booked resources from bookit."""
    result = subprocess.run(
        ['bookit', '--status-json'],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)['resources']['booked']['current']


def _book_one(resource_type: str, query: str, message: str, end_iso: str) -> str:
    """Book one resource, queuing and waiting until one is available.

    Runs bookit with its output visible (queue position, credential prompts,
    etc.), then reads the booked name back via --status-json.
    """
    cmd = [
        'bookit',
        '--type', resource_type,
        '--book', '--queue', '--wait',
        query,
        '--book-email',
        '--message', message,
        '--end', end_iso,
    ]
    subprocess.run(cmd, check=True)

    for resource in _bookit_current():
        if resource.get('comment') == message:
            return resource['name']
    raise RuntimeError(
        f'Could not find booked {resource_type} with comment {message!r}'
    )


def _try_book_one(
    resource_type: str, query: str, message: str, end_iso: str,
) -> str | None:
    """Try to book one resource without waiting; return its name or None.

    Uses --queue but not --wait so bookit exits immediately if no resource
    is free rather than blocking indefinitely.  Output is captured to
    prevent bookit from dropping into its interactive menu.
    """
    cmd = [
        'bookit',
        '--type', resource_type,
        '--book', '--queue',
        query,
        '--book-email',
        '--message', message,
        '--end', end_iso,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    for resource in _bookit_current():
        if resource.get('comment') == message:
            return resource['name']
    return None


def book_resources(
    n_brokers: int,
    n_perfhosts: int,
    vmr_query: str,
    perf_query: str,
    duration_hours: float,
    run_tag: str,
    booked_items: list[tuple[str, str]],
) -> tuple[list[str], list[str]]:
    """Book n_brokers VMRs and n_perfhosts perf-hosts; return (brokers, ips).

    Each successfully booked resource is appended to booked_items immediately,
    so the caller can free partial results if interrupted mid-booking.
    """
    end_iso = (
        dt.datetime.now() + dt.timedelta(hours=duration_hours)
    ).isoformat(timespec='minutes')

    brokers: list[str] = []
    for i in range(n_brokers):
        comment = f'{run_tag}-vmr-{i + 1}'
        print(f'  Booking VMR {i + 1}/{n_brokers} (comment: {comment}) ...')
        name = _book_one('vmr', vmr_query, comment, end_iso)
        print(f'  Booked: {name}')
        brokers.append(name)
        booked_items.append(('vmr', name))

    perf_ips: list[str] = []
    for i in range(n_perfhosts):
        comment = f'{run_tag}-perf-{i + 1}'
        print(f'  Booking perf-host {i + 1}/{n_perfhosts} (comment: {comment}) ...')
        name = _try_book_one('perf-host', perf_query, comment, end_iso)
        if name is not None:
            print(f'  Booked: {name}')
            perf_ips.append(normalize_to_ip(name))
            booked_items.append(('perf-host', name))
        else:
            print(f'  No perf-host available for query {perf_query!r}.')
            raw = input(
                f'  Enter perf-host {i + 1}/{n_perfhosts} hostname or IP: '
            ).strip()
            perf_ips.append(normalize_to_ip(raw))

    return brokers, perf_ips


def free_resources(booked_items: list[tuple[str, str]]) -> None:
    """Free all booked resources via bookit --free."""
    for resource_type, name in booked_items:
        print(f'  Freeing {resource_type} {name} ...')
        try:
            subprocess.run(
                ['bookit', '--type', resource_type, '--free', name],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f'  WARNING: could not free {name}: {exc}')


def prompt_book_resources(
    sting: dict,
    run: dict,
    child_id: str,
    booked_items: list[tuple[str, str]],
) -> tuple[list[str], list[str], list[str]] | None:
    """Offer to auto-book resources.

    Appends each booked resource to booked_items as it is acquired so the
    caller can free partial results on interruption.  Returns
    (brokers, monitor, perf_ips) or None if the user declines.
    """
    answer = input('\nAuto-book resources via bookit? [y/N] ').strip().lower()
    if answer != 'y':
        return None

    n_brokers = len(sting['brokers'])
    n_perf = len(run['phosts'])

    raw = input(f'  Booking duration in hours [4]: ').strip()
    duration = float(raw) if raw else 4.0

    raw = input(f'  VMR query [{n_brokers} needed, default "*"]: ').strip()
    vmr_query = raw or '*'

    raw = input(f'  Perf-host query [{n_perf} needed, default "*"]: ').strip()
    perf_query = raw or '*'

    run_tag = f'rerun-afw-{child_id}'
    print()
    brokers, perf_ips = book_resources(
        n_brokers, n_perf, vmr_query, perf_query, duration, run_tag, booked_items,
    )

    print(f'\n  Booked brokers   : {", ".join(brokers)}')
    print(f'  Booked perf hosts: {", ".join(display_perf(ip) for ip in perf_ips)}')

    monitor = prompt_monitor(brokers, sting['monitor'])
    return brokers, monitor, perf_ips


# ---------------------------------------------------------------------------
# Discrepancy report
# ---------------------------------------------------------------------------

def report_discrepancies(
    sting: dict,
    run: dict,
    new_brokers: list[str],
    new_monitor: list[str],
    new_phosts: list[str],
) -> None:
    """Print warnings for anything that differs in count from the original."""
    warnings: list[str] = []

    orig_brokers = sting['brokers']
    if len(new_brokers) != len(orig_brokers):
        warnings.append(
            f'broker count: original had {len(orig_brokers)}'
            f', new has {len(new_brokers)}'
        )

    orig_monitor = sting['monitor']
    if len(new_monitor) != len(orig_monitor):
        warnings.append(
            f'monitoring-node count: original had {len(orig_monitor)}'
            f', new has {len(new_monitor)}'
        )

    orig_phosts = run['phosts']
    if len(new_phosts) != len(orig_phosts):
        warnings.append(
            f'perf-host count: original had {len(orig_phosts)}'
            f', new has {len(new_phosts)}'
        )

    if warnings:
        print('\n--- Discrepancies ---')
        for w in warnings:
            print(f'  WARNING: {w}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        'url', metavar='URL',
        help='AFW summary page URL, e.g. https://internal.soltest.net/summary.php?ChildID=NNNN',
    )
    ap.add_argument(
        '--dry-run', action='store_true',
        help='Print the new commands but do not execute them',
    )
    args = ap.parse_args()

    print(f'Fetching {args.url} ...')
    sting_raw, run_raw = fetch_commands(args.url)

    try:
        sting = parse_sting_vmr(sting_raw)
    except ValueError as exc:
        sys.exit(f'ERROR parsing Setup command: {exc}')

    run = parse_run_automation(run_raw)

    child_id_m = re.search(r'ChildID=(\d+)', args.url, re.IGNORECASE)
    child_id = child_id_m.group(1) if child_id_m else 'unknown'

    print('\n--- Original resources ---')
    print(f'  Brokers    : {", ".join(sting["brokers"])}')
    print(f'  Monitoring : {", ".join(sting["monitor"]) or "(none)"}')
    print(f'  Version    : {sting["version"]}')
    print(f'  Perf hosts : {", ".join(display_perf(ip) for ip in run["phosts"])}')

    booked_items: list[tuple[str, str]] = []

    def _offer_free() -> None:
        if not booked_items:
            return
        answer = input('\nFree booked resources? [Y/n] ').strip().lower()
        if answer != 'n':
            free_resources(booked_items)

    try:
        booked = prompt_book_resources(sting, run, child_id, booked_items)
        if booked is not None:
            new_brokers, new_monitor, new_phosts = booked
        else:
            print('\n--- New resources ---')
            new_brokers = prompt_split('brokers', sting['brokers'])
            new_monitor = prompt_monitor(new_brokers, sting['monitor'])
            new_phosts  = prompt_perf_hosts(run['phosts'])

        if not new_phosts:
            sys.exit('ERROR: at least one perf host is required')

        report_discrepancies(sting, run, new_brokers, new_monitor, new_phosts)

        # First perf host drives -perfHost / -toolIp in scriptArgs
        new_perf_host_ip = new_phosts[0]

        raw = input(f'\n  Broker load version [{sting["version"]}]: ').strip()
        version = raw if raw else sting['version']

        new_sting = build_sting_vmr(sting, new_brokers, new_monitor, version)
        new_run   = build_run_automation(run, new_brokers, new_phosts, new_perf_host_ip)

        scripts_dir = prompt_scripts_dir()
        if scripts_dir is not None:
            new_run = localize_run_automation(new_run, scripts_dir)

        print('\n--- New commands ---')
        print(f'\n[1] {new_sting}')
        if scripts_dir is not None:
            print(f'\n[2] (run from {scripts_dir}, SOL_AFW_CURRENT_LIB={scripts_dir.parent})')
        print(f'    {new_run}')

        run_sting = input('\nRun sting-vmr? [y/N] ').strip().lower() == 'y'

        if args.dry_run:
            print('\n(dry-run: not executing)')
            _offer_free()
            return

        answer = input('Run these commands? [y/N] ').strip().lower()
        if answer != 'y':
            print('Aborted.')
            _offer_free()
            return

        if run_sting:
            print('\n=== Running sting-vmr ===')
            subprocess.run(shlex.split(new_sting), check=True)
        else:
            print('Skipping sting-vmr.')

        print('\n=== Running runAutomation ===')
        if scripts_dir is not None:
            e2e_dir = shlex.quote(str(scripts_dir.parent))
            bash_cmd = (
                f'export SOL_AFW_CURRENT_LIB={e2e_dir} && '
                f'source "$SOL_AFW_CURRENT_LIB/envInfo/.bashrc.afw.tcllib" && '
                f'cd {shlex.quote(str(scripts_dir))} && '
                f'{new_run}'
            )
            subprocess.run(['bash', '-c', bash_cmd], check=True)
        else:
            subprocess.run(shlex.split(new_run), check=True)

    except KeyboardInterrupt:
        print('\nInterrupted.')
        _offer_free()
        sys.exit(1)


if __name__ == '__main__':
    main()
