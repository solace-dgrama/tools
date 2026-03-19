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
import shutil
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
# Load availability helpers
# ---------------------------------------------------------------------------

_LOADS_BASE = Path('/home/public/RND/loads/solcbr')


def _strip_soltr(version: str) -> str:
    """Strip 'soltr_' prefix from a load version string."""
    return version.removeprefix('soltr_')


def _load_path(version: str) -> Path | None:
    """Return the expected filesystem path for a load, or None if unparseable.

    Three layouts are supported:
        regular: _LOADS_BASE/<X.Y.Z>/<X.Y.Z.BUILD>/   e.g. 10.25.0.202
        feature: _LOADS_BASE/feature/<NAME>/<VERSION>/ e.g. 100.0SOL-144552.0.5612
        main:    _LOADS_BASE/main/<VERSION>/           e.g. 100.0main.0.5554

    The type is determined by the second dotted segment: purely numeric → regular;
    'main' → main; anything else → feature (name = second segment minus leading digits).
    """
    v = _strip_soltr(version)
    parts = v.split('.')
    if len(parts) < 2:
        return None
    branch = re.sub(r'^\d+', '', parts[1])   # '' for regular, 'main', 'SOL-144552', …
    if branch == 'main':
        return _LOADS_BASE / 'main' / v
    if branch:
        return _LOADS_BASE / 'feature' / branch / v
    # Regular release
    dot = v.rfind('.')
    return _LOADS_BASE / v[:dot] / v


def _version_display(version: str) -> str:
    """Version string for display: no 'soltr_' prefix, with availability note."""
    display = _strip_soltr(version)
    path = _load_path(version)
    if path is not None and not path.exists():
        return f'{display} (unavailable)'
    return display


def _latest_build(parent_dir: Path) -> str | None:
    """Return the version name of the latest build in a parent directory.

    Prefers the 'current' symlink; falls back to the highest build number.
    """
    current = parent_dir / 'current'
    if current.is_symlink():
        target = current.resolve()
        if target.is_dir():
            return target.name

    builds = []
    try:
        for d in parent_dir.iterdir():
            if d.is_dir() and d.name not in ('current', 'previous'):
                builds.append(d.name)
    except OSError:
        return None
    if not builds:
        return None

    def _build_key(name: str) -> int:
        try:
            return int(name.rsplit('.', 1)[-1])
        except ValueError:
            return -1

    return max(builds, key=_build_key)


def _find_load_candidates(partial: str) -> list[str]:
    """Return the latest build version from each directory whose name contains
    `partial` (case-insensitive).

    Searches both the top-level version dirs (regular releases) and one level
    inside the 'feature' and 'main' group directories.
    """
    needle = _strip_soltr(partial).lower()
    seen: set[str] = set()
    candidates: list[str] = []

    def _add(version: str) -> None:
        if version not in seen:
            seen.add(version)
            candidates.append(version)

    try:
        for entry in sorted(_LOADS_BASE.iterdir()):
            if not entry.is_dir():
                continue
            if needle in entry.name.lower():
                # Direct top-level match (e.g. '10.25.0' matches '10.25')
                latest = _latest_build(entry)
                if latest:
                    _add(latest)
            elif entry.name in ('feature', 'main'):
                # Search one level inside group directories
                for sub in sorted(entry.iterdir()):
                    if sub.is_dir() and needle in sub.name.lower():
                        latest = _latest_build(sub)
                        if latest:
                            _add(latest)
    except OSError:
        pass
    return candidates


# ---------------------------------------------------------------------------
# Fetch commands from the AFW summary page
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def fetch_commands(url: str) -> tuple[str | None, str, str | None, list[str]]:
    """Return (sting_cmd, run_cmd, load_version, orig_perf_types) from an AFW summary page.

    sting_cmd and load_version may be None if absent from the page.
    orig_perf_types is a list of 'OS OS_version' strings (one per perf host, in order).
    """
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

    sting_cmd    = extract('Setup')
    load_version = extract('Load')
    # 'Test Script Command Line' has the full -scriptArgs; prefer it over
    # the parent-level 'Command Line' which may use &quot; encoding.
    run_cmd = extract('Test Script Command Line') or extract('Command Line')

    if not sting_cmd:
        print('WARNING: "Setup" field not found on the page.')
    if not run_cmd:
        sys.exit('ERROR: runAutomation command not found on the page')

    # Parse the PerfHosts section for original perf-host type strings.
    # Each entry looks like: <a href="...">192.168.x.y</a> (N) - OS OS_version<br>
    orig_perf_types: list[str] = []
    perf_hosts_m = re.search(
        r'<b>PerfHosts</b>\s*:\s*</td><td>(.*?)</td>',
        body, re.DOTALL,
    )
    if perf_hosts_m:
        for m in re.finditer(
            r'<a[^>]*>[\d.]+</a>\s+\(\d+\)\s+-\s+([^<]+)',
            perf_hosts_m.group(1),
        ):
            orig_perf_types.append(html.unescape(m.group(1).strip()))

    return sting_cmd, run_cmd, load_version, orig_perf_types


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

    parts = parsed['pre'] + new_brokers + [_strip_soltr(version)] + new_opts
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
    e2e_dir = scripts_dir
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
    """Ask where the local scripts directory is (SOL_AFW_CURRENT_LIB)."""
    default = Path('.')
    hint = f' [{default.resolve()}]'
    raw = input(f'\n  Local scripts directory{hint}: ').strip()
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
# Sting-vmr from scratch
# ---------------------------------------------------------------------------

_DEFAULT_STING_OPTS = (
    '--vmr-type enterprise --scaling-max-connections auto '
    '--scaling-max-queue-messages auto --docker-os redhat '
    '--docker-config vmr_docker_prod1 --docker-user 1000001 '
    '--docker-network host --use-environment-variables'
)


def _find_afw_tools() -> 'str | None':
    found = shutil.which('afw-tools')
    if found:
        return found
    fallback = '/home/automation/bin/afw-tools'
    if Path(fallback).exists():
        return fallback
    return None


def _get_sting_vmr_help() -> str:
    sting_vmr = shutil.which('sting-vmr') or '/home/automation/bin/sting-vmr'
    try:
        result = subprocess.run(
            [sting_vmr, '-h'],
            capture_output=True, text=True, timeout=15,
        )
        return (result.stdout + result.stderr).strip()
    except Exception:
        return ''


def _parse_known_flags(help_text: str) -> 'set[str]':
    return set(re.findall(r'--[\w-]+', help_text))


def _sanitize_sting_opts(opts_tokens: list, known_flags: set) -> list:
    """Return list of unknown --flag names found in opts_tokens."""
    unknown = []
    for token in opts_tokens:
        if token.startswith('--') and token not in known_flags:
            unknown.append(token)
    if unknown:
        print(f'  WARNING: unrecognised flags: {", ".join(unknown)}')
    return unknown


def _assemble_sting_from_scratch(
    afw_tools: str, brokers: list, monitor: list, version: str, opts_tokens: list,
) -> str:
    parts = [afw_tools, 'sting-vmr'] + brokers + [_strip_soltr(version)]
    if monitor:
        parts += ['--monitoring-nodes', ','.join(monitor)]
    parts += opts_tokens
    return ' '.join(shlex.quote(t) for t in parts)


def _prompt_version(load_version: 'str | None') -> str:
    """Prompt for a broker load version with fuzzy matching. Returns the chosen version (may be empty)."""
    if not load_version:
        print('  WARNING: "Load" field not found on the page.')
    hint_v = _strip_soltr(load_version) if load_version else ''
    hint = f' [{hint_v}]' if hint_v else ''
    while True:
        raw = input(f'\n  Broker load version{hint}: ').strip()
        version = raw if raw else load_version or ''
        if not version:
            return version

        lpath = _load_path(version)
        if lpath is not None and lpath.is_dir():
            return version

        candidates = _find_load_candidates(version)
        if not candidates:
            print(f'  ERROR: {_strip_soltr(version)!r} not found. Please try again.')
            hint = f' [{_strip_soltr(version)}]'
            continue

        if len(candidates) == 1:
            ans = input(f'  Use {candidates[0]}? [Y/n] ').strip().lower()
            if ans != 'n':
                return candidates[0]
            hint = f' [{_strip_soltr(version)}]'
            continue

        print('  Matching loads:')
        for i, c in enumerate(candidates, 1):
            print(f'    [{i}] {c}')
        while True:
            sel = input(f'  Select [1-{len(candidates)}] or Enter to retry: ').strip()
            if not sel:
                hint = f' [{_strip_soltr(version)}]'
                break
            if sel.isdigit() and 1 <= int(sel) <= len(candidates):
                return candidates[int(sel) - 1]
            print(f'  Enter a number between 1 and {len(candidates)}.')


def prompt_sting_from_scratch(new_brokers: list) -> 'tuple | None':
    """Interactively build a sting-vmr invocation from scratch.

    Returns (sting_brokers, monitor_nodes, opts_tokens, afw_tools_path) or
    None if user declines.
    """
    ans = input('\nNo sting-vmr command in the original run. Build one now? [y/N] ').strip().lower()
    if ans != 'y':
        return None

    afw_tools = _find_afw_tools()
    if afw_tools is None:
        raw = input(
            '  afw-tools not found. Path [/home/automation/bin/afw-tools]: '
        ).strip()
        afw_tools = raw if raw else '/home/automation/bin/afw-tools'
        if not Path(afw_tools).exists():
            print(f'  WARNING: {afw_tools!r} does not exist.')

    broker_str = ', '.join(new_brokers)
    raw = input(f'\n  Brokers to sting ({broker_str}) : ').strip()
    sting_brokers = [h for h in re.split(r'[,\s]+', raw) if h] if raw else list(new_brokers)

    sting_set = set(sting_brokers)
    while True:
        raw = input('  Monitoring node(s) (space or comma separated): ').strip()
        monitor = [h for h in re.split(r'[,\s]+', raw) if h]
        dups = _duplicates(monitor)
        if dups:
            print(f'  ERROR: duplicates: {", ".join(dups)}. Please try again.')
            continue
        outside = [n for n in monitor if n not in sting_set]
        if outside:
            print(f'  ERROR: not in broker list: {", ".join(outside)}. Please try again.')
            continue
        break

    show_help = input("\n  Show 'sting-vmr -h' output? [y/N] ").strip().lower()
    if show_help == 'y':
        help_text = _get_sting_vmr_help()
        if help_text:
            print(help_text)
        else:
            print('  (Help unavailable. Run: sting-vmr -h)')
    else:
        help_text = None

    print(f'\n  Default options: {_DEFAULT_STING_OPTS}')

    while True:
        raw = input('  Options (Enter to accept defaults): ').strip()
        opts_tokens = shlex.split(raw) if raw else shlex.split(_DEFAULT_STING_OPTS)

        if help_text is None:
            help_text = _get_sting_vmr_help()
        known_flags = _parse_known_flags(help_text) if help_text else set()

        if known_flags:
            unknown = _sanitize_sting_opts(opts_tokens, known_flags)
            if unknown:
                keep = input('  Keep unknown options? [y/N] ').strip().lower()
                if keep != 'y':
                    continue

        break

    return sting_brokers, monitor, opts_tokens, afw_tools


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
    broker_query: str,
    perf_query: str,
    duration_hours: float,
    run_tag: str,
    booked_items: list[tuple[str, str]],
    broker_type: str = 'vmr',
    booking_message: str = 'afw troubleshooting',
) -> tuple[list[str], list[str]]:
    """Book n_brokers broker resources and n_perfhosts perf-hosts; return (brokers, ips).

    Each successfully booked resource is appended to booked_items immediately,
    so the caller can free partial results if interrupted mid-booking.
    The booking_message is stored as the bookit comment, with a unique slot tag
    appended so each booking can be identified after the fact.
    """
    end_iso = (
        dt.datetime.now() + dt.timedelta(hours=duration_hours)
    ).isoformat(timespec='minutes')

    brokers: list[str] = []
    for i in range(n_brokers):
        comment = f'{booking_message} [{run_tag}-broker-{i + 1}]'
        print(f'  Booking broker {i + 1}/{n_brokers} (comment: {comment}) ...')
        name = _try_book_one(broker_type, broker_query, comment, end_iso)
        if name is None and broker_query != '*':
            print(f'    No match for {broker_query!r}; trying any {broker_type} ...')
            name = _try_book_one(broker_type, '*', comment, end_iso)
        if name is not None:
            print(f'    Booked: {name}')
            brokers.append(name)
            booked_items.append((broker_type, name))
        else:
            print(f'    No {broker_type} available.')
            raw = input(
                f'    Enter broker {i + 1}/{n_brokers} name (or leave empty to skip): '
            ).strip()
            if raw:
                brokers.append(raw)

    perf_ips: list[str] = []
    for i in range(n_perfhosts):
        comment = f'{booking_message} [{run_tag}-perf-{i + 1}]'
        print(f'  Booking perf-host {i + 1}/{n_perfhosts} (comment: {comment}) ...')
        name = _try_book_one('perf-host', perf_query, comment, end_iso)
        if name is None and perf_query != '*':
            print(f'    No match for {perf_query!r}; trying any perf-host ...')
            name = _try_book_one('perf-host', '*', comment, end_iso)
        if name is not None:
            print(f'    Booked: {name}')
            perf_ips.append(normalize_to_ip(name))
            booked_items.append(('perf-host', name))
        else:
            print(f'    No perf-host available.')
            raw = input(
                f'    Enter perf-host {i + 1}/{n_perfhosts} hostname or IP (or leave empty to skip): '
            ).strip()
            if raw:
                perf_ips.append(normalize_to_ip(raw))

    return brokers, perf_ips


def _warn_unowned_resources(
    names: list[str], resource_type: str, booked_names: set[str],
) -> bool:
    """Warn if any of the given resources are not in booked_names.

    For perf-hosts, both hostname (perf-A-B) and IP (192.168.A.B) forms are
    accepted as evidence of ownership.  Returns True if any unowned resources
    were found.
    """
    unowned = []
    for name in names:
        if resource_type == 'perf-host':
            ip       = normalize_to_ip(name)
            hostname = ip_to_perf_host(ip)
            if name not in booked_names and ip not in booked_names and hostname not in booked_names:
                unowned.append(name)
        else:
            if name not in booked_names:
                unowned.append(name)

    if unowned:
        label = 'broker' if resource_type in ('vmr', 'appliance') else resource_type
        display = (
            [display_perf(normalize_to_ip(n)) for n in unowned]
            if resource_type == 'perf-host' else unowned
        )
        print(f'\n  WARNING: the following {label}(s) do not appear to be booked by you:')
        for d in display:
            print(f'    {d}')

    return bool(unowned)


# ---------------------------------------------------------------------------
# Resource type helpers
# ---------------------------------------------------------------------------

def _bookit_get_attr(resource_type: str, name: str, attr: str) -> str | None:
    """Return a single bookit attribute value for a resource, or None on error."""
    try:
        result = subprocess.run(
            ['bookit', '--type', resource_type, '--get-attribute', attr, name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def _resolve_broker_type(name: str) -> str | None:
    """Determine the bookit resource type for a broker by querying bookit.

    Tries 'vmr' first (checking num_cpus), then 'appliance' (checking platform).
    Returns 'vmr', 'appliance', or None if the resource is not found in either.
    """
    if _bookit_get_attr('vmr', name, 'num_cpus') is not None:
        return 'vmr'
    if _bookit_get_attr('appliance', name, 'platform') is not None:
        return 'appliance'
    return None


def _broker_type_desc(name: str) -> str | None:
    """Return a short type description for a broker by querying bookit, or None.

    Resolves the resource type against bookit first (no name-pattern assumptions).
    VMRs return 'N cores, X GiB RAM'; appliances return 'platform [sub_platform]'.
    """
    btype = _resolve_broker_type(name)
    if btype == 'vmr':
        cpus = _bookit_get_attr('vmr', name, 'num_cpus')
        ram  = _bookit_get_attr('vmr', name, 'ram')
        if cpus and ram:
            return f'{cpus} cores, {ram} GiB RAM'
    elif btype == 'appliance':
        platform     = _bookit_get_attr('appliance', name, 'platform')
        sub_platform = _bookit_get_attr('appliance', name, 'sub_platform')
        if platform:
            return f'{platform} {sub_platform}'.strip() if sub_platform else platform
    return None


def _perf_host_type_desc(name_or_ip: str) -> str | None:
    """Return 'OS OS_version' for a perf host from bookit, or None if unavailable."""
    hostname = ip_to_perf_host(normalize_to_ip(name_or_ip))
    os_val = _bookit_get_attr('perf-host', hostname, 'OS')
    os_ver = _bookit_get_attr('perf-host', hostname, 'OS_version')
    parts = [p for p in (os_val, os_ver) if p]
    return ' '.join(parts) if parts else None


def _broker_booking_query(type_desc: str | None, broker_type: str) -> str:
    """Build a bookit broker query from a type description string, or return '*'."""
    if not type_desc:
        return '*'
    if broker_type == 'vmr':
        m = re.match(r'(\d+)\s+cores,\s+([\d.]+)\s+GiB', type_desc)
        return f'num_cpus:{m.group(1)} ram:{m.group(2)}' if m else '*'
    # Appliance: description is 'platform [sub_platform]'
    parts = type_desc.split(None, 1)
    if len(parts) == 2:
        return f'platform:{parts[0]} sub_platform:{parts[1]}'
    if len(parts) == 1:
        return f'platform:{parts[0]}'
    return '*'


def _perf_booking_query(type_desc: str | None) -> str:
    """Build a bookit perf-host query from a type description string, or return '*'."""
    if not type_desc:
        return '*'
    parts = type_desc.split()
    if len(parts) >= 2:
        return f'OS:{parts[0]} OS_version:{parts[1]}'
    if len(parts) == 1:
        return f'OS:{parts[0]}'
    return '*'


def _type_desc_from_attrs(rtype: str, attrs: dict) -> str | None:
    """Extract a short type description from a bookit status-json attrs dict.

    The attrs dict is expected to map attribute names to dicts with a 'value'
    key (the format used in bookit's --status-json output).  Returns None if
    the relevant attributes are absent.
    """
    if not attrs:
        return None

    def _val(key: str) -> str:
        entry = attrs.get(key)
        if isinstance(entry, dict):
            return entry.get('value', '') or ''
        return str(entry) if entry else ''

    rtype_lower = rtype.lower()
    if rtype_lower == 'vmr':
        cpus = _val('num_cpus')
        ram  = _val('ram')
        if cpus and ram:
            return f'{cpus} cores, {ram} GiB RAM'
    elif rtype_lower == 'appliance':
        platform     = _val('platform')
        sub_platform = _val('sub_platform')
        if platform:
            return f'{platform} {sub_platform}'.strip() if sub_platform else platform
    elif rtype_lower in ('perfhost', 'perf-host'):
        os_val = _val('OS')
        os_ver = _val('OS_version')
        parts = [p for p in (os_val, os_ver) if p]
        return ' '.join(parts) if parts else None
    return None


def _resource_type_desc(r: dict) -> str | None:
    """Return a type description for a resource dict from _bookit_current().

    Uses attrs embedded in the status-json resource entry; no extra bookit
    calls are made.
    """
    return _type_desc_from_attrs(r.get('type', ''), r.get('attrs', {}))


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
    sting: dict | None,
    run: dict,
    child_id: str,
    booked_items: list[tuple[str, str]],
    orig_perf_types: list[str],
) -> tuple[list[str], list[str], list[str]] | None:
    """Offer to auto-book resources.

    Appends each booked resource to booked_items as it is acquired so the
    caller can free partial results on interruption.  Returns
    (brokers, monitor, perf_ips) or None if the user declines.
    """
    # Show resources already owned by the user so they can make an informed choice.
    # Brokers (VMR, Appliance, COTS) sort first, then other types; within each type by name.
    _BROKER_TYPES = {'VMR', 'Appliance', 'COTS'}

    def _resource_sort_key(r: dict) -> tuple:
        rtype = r.get('type', '')
        return (0 if rtype in _BROKER_TYPES else 1, rtype, r.get('name', ''))

    try:
        current = _bookit_current()
        if current:
            print('\n  Your current bookit resources:')
            for r in sorted(current, key=_resource_sort_key):
                end   = r.get('end', '?')
                rtype = r.get('type', '')
                name  = r['name']
                # Show perf hosts as "IP (hostname)" to match the original resources format
                if rtype.lower() in ('perfhost', 'perf-host') and _PERF_HOST_RE.match(name):
                    display_name = display_perf(perf_host_to_ip(name))
                else:
                    display_name = name
                desc   = _resource_type_desc(r)
                detail = f' - {desc.replace(chr(10), " ").strip()}' if desc else ''
                print(f'    {display_name}{detail} [{end}]')
        else:
            print('\n  You have no resources currently booked in bookit.')
    except Exception:
        print('\n  (Could not fetch current bookit resources.)')

    answer = input('\nAuto-book resources via bookit? [y/N] ').strip().lower()
    if answer != 'y':
        return None

    orig_brokers = sting['brokers'] if sting else run['hosts']
    n_brokers = len(orig_brokers)
    n_perf = len(run['phosts'])

    raw = input('  Booking duration in hours [4]: ').strip()
    duration = float(raw) if raw else 4.0

    raw = input('  Booking message ["afw troubleshooting"]: ').strip()
    booking_message = raw or 'afw troubleshooting'

    # Look up original resource types per broker to suggest matching booking queries.
    print('  Looking up original resource types ...')
    orig_broker_types = [_broker_type_desc(b) for b in orig_brokers]
    orig_perf_type_list = [
        (orig_perf_types[i] if i < len(orig_perf_types)
         else _perf_host_type_desc(run['phosts'][i]))
        for i in range(len(run['phosts']))
    ]

    for b, t in zip(orig_brokers, orig_broker_types):
        print(f'  Original broker type   : {b} -> {t or "(unknown)"}')
    for ip, t in zip(run['phosts'], orig_perf_type_list):
        print(f'  Original perf-host type: {display_perf(ip)} -> {t or "(unknown)"}')

    # Use the first resolved type to build the default booking query.
    first_orig_broker = orig_brokers[0] if orig_brokers else None
    broker_type       = (_resolve_broker_type(first_orig_broker) or 'vmr') if first_orig_broker else 'vmr'
    first_broker_type = orig_broker_types[0] if orig_broker_types else None
    orig_perf_type    = orig_perf_type_list[0] if orig_perf_type_list else None

    default_broker_q = _broker_booking_query(first_broker_type, broker_type)
    default_perf_q   = _perf_booking_query(orig_perf_type)

    raw = input(f'  Broker query [{n_brokers} needed, default "{default_broker_q}"]: ').strip()
    broker_query = raw or default_broker_q

    raw = input(f'  Perf-host query [{n_perf} needed, default "{default_perf_q}"]: ').strip()
    perf_query = raw or default_perf_q

    run_tag = f'rerun-afw-{child_id}'
    print()
    brokers, perf_ips = book_resources(
        n_brokers, n_perf, broker_query, perf_query, duration, run_tag, booked_items,
        broker_type=broker_type, booking_message=booking_message,
    )

    print(f'\n  Booked brokers   : {", ".join(brokers)}')
    print(f'  Booked perf hosts: {", ".join(display_perf(ip) for ip in perf_ips)}')

    monitor = prompt_monitor(brokers, sting['monitor']) if sting else []
    return brokers, monitor, perf_ips


# ---------------------------------------------------------------------------
# Discrepancy report
# ---------------------------------------------------------------------------


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
    sting_raw, run_raw, load_version, orig_perf_types = fetch_commands(args.url)

    sting = None
    if sting_raw is not None:
        try:
            sting = parse_sting_vmr(sting_raw)
        except ValueError as exc:
            sys.exit(f'ERROR parsing Setup command: {exc}')

    run = parse_run_automation(run_raw)

    child_id_m = re.search(r'ChildID=(\d+)', args.url, re.IGNORECASE)
    child_id = child_id_m.group(1) if child_id_m else 'unknown'

    print('\n--- Original resources ---')
    v_str = _version_display(load_version) if load_version else '(not found)'
    orig_broker_list = sting['brokers'] if sting else run['hosts']
    monitor_set = set(sting['monitor']) if sting else set()
    print('  Brokers (looking up types):')
    for b in orig_broker_list:
        desc   = _broker_type_desc(b)
        detail = f' - {desc}' if desc else ''
        tag    = ' [monitoring]' if b in monitor_set else ''
        print(f'    {b}{detail}{tag}')
    print(f'  Version    : {v_str}')
    print('  Perf hosts:')
    for i, ip in enumerate(run['phosts']):
        disp   = display_perf(ip)
        detail = f' - {orig_perf_types[i]}' if i < len(orig_perf_types) else ''
        print(f'    {disp}{detail}')

    booked_items: list[tuple[str, str]] = []

    def _offer_free() -> None:
        if not booked_items:
            return
        answer = input('\nFree booked resources? [Y/n] ').strip().lower()
        if answer != 'n':
            free_resources(booked_items)

    try:
        orig_brokers = sting['brokers'] if sting else run['hosts']
        orig_monitor = sting['monitor'] if sting else []

        booked = prompt_book_resources(sting, run, child_id, booked_items, orig_perf_types)
        if booked is not None:
            new_brokers, new_monitor, new_phosts = booked
        else:
            print('\n--- New resources ---')
            new_brokers = prompt_split('brokers', orig_brokers)
            new_monitor = prompt_monitor(new_brokers, orig_monitor) if sting else []
            new_phosts  = prompt_perf_hosts(run['phosts'])

        built_sting_opts: list | None = None
        afw_tools_for_sting: str | None = None
        built_sting_brokers: list | None = None
        if sting is None:
            result = prompt_sting_from_scratch(new_brokers)
            if result is not None:
                built_sting_brokers, new_monitor, built_sting_opts, afw_tools_for_sting = result

        warnings = []
        if len(new_brokers) != len(orig_brokers):
            warnings.append(f'brokers: {len(new_brokers)}/{len(orig_brokers)}')
        if sting and len(new_monitor) != len(orig_monitor):
            warnings.append(f'monitoring nodes: {len(new_monitor)}/{len(orig_monitor)}')
        if len(new_phosts) != len(run['phosts']):
            warnings.append(f'perf hosts: {len(new_phosts)}/{len(run["phosts"])}')
        if warnings:
            print('\nWARNING: resources do not match the original:')
            for w in warnings:
                print(f'  {w}')
            if input('Continue anyway? [y/N] ').strip().lower() != 'y':
                _offer_free()
                return

        # First perf host drives -perfHost / -toolIp in scriptArgs
        new_perf_host_ip = new_phosts[0] if new_phosts else ''

        if sting:
            version = _prompt_version(load_version)
            new_sting = build_sting_vmr(sting, new_brokers, new_monitor, version)
        elif built_sting_opts is not None:
            while True:
                version = _prompt_version(load_version)
                new_sting = _assemble_sting_from_scratch(
                    afw_tools_for_sting, built_sting_brokers, new_monitor, version, built_sting_opts,
                )
                print(f'\n  sting-vmr command:\n    {new_sting}')
                if input('  Happy with this command? [Y/n] ').strip().lower() != 'n':
                    break
                result = prompt_sting_from_scratch(new_brokers)
                if result is None:
                    built_sting_opts = None
                    version = None
                    new_sting = None
                    break
                built_sting_brokers, new_monitor, built_sting_opts, afw_tools_for_sting = result
        else:
            version = None
            new_sting = None

        new_run = build_run_automation(run, new_brokers, new_phosts, new_perf_host_ip)

        scripts_dir = prompt_scripts_dir()
        if scripts_dir is not None:
            new_run = localize_run_automation(new_run, scripts_dir)

        print('\n--- New resources ---')
        print(f'  Brokers    : {", ".join(new_brokers)}')
        if sting or built_sting_opts is not None:
            print(f'  Monitoring : {", ".join(new_monitor) or "(none)"}')
            print(f'  Version    : {_strip_soltr(version)}')
        print(f'  Perf hosts : {", ".join(display_perf(ip) for ip in new_phosts)}')
        lib_val = str(scripts_dir) if scripts_dir is not None else '(not set)'
        run_dir = str(scripts_dir / 'scripts') if scripts_dir is not None else '(not set)'
        print(f'  SOL_AFW_CURRENT_LIB={lib_val}')
        print(f'  Run directory      : {run_dir}')

        try:
            booked_names: set[str] = {r['name'] for r in _bookit_current()}
        except Exception:
            print('\n  WARNING: bookit unavailable; resource ownership could not be verified.')
            booked_names = None

        if booked_names is not None:
            detected_broker_type = (_resolve_broker_type(new_brokers[0]) or 'vmr') if new_brokers else 'vmr'
            broker_warn = _warn_unowned_resources(new_brokers, detected_broker_type, booked_names)
            perf_warn   = _warn_unowned_resources(new_phosts, 'perf-host', booked_names)
        if booked_names is not None and (broker_warn or perf_warn):
            if input('\nContinue with unowned resources? [y/N] ').strip().lower() != 'y':
                _offer_free()
                return

        # Check resource type compatibility per position against the original test.
        type_warnings: list[str] = []
        for i, broker in enumerate(new_brokers):
            orig = orig_brokers[i] if i < len(orig_brokers) else None
            if orig is None:
                continue
            orig_t = _broker_type_desc(orig)
            new_t  = _broker_type_desc(broker)
            if orig_t and new_t and orig_t != new_t:
                type_warnings.append(
                    f'  Broker {broker}: {new_t} (original {orig}: {orig_t})'
                )
        for i, ip in enumerate(new_phosts):
            if i < len(orig_perf_types):
                orig_t = orig_perf_types[i]
            elif i < len(run['phosts']):
                orig_t = _perf_host_type_desc(run['phosts'][i])
            else:
                orig_t = None
            if orig_t is None:
                continue
            new_t = _perf_host_type_desc(ip)
            if new_t and new_t != orig_t:
                orig_display = (display_perf(run['phosts'][i])
                                if i < len(run['phosts']) else '?')
                type_warnings.append(
                    f'  Perf host {display_perf(ip)}: {new_t}'
                    f' (original {orig_display}: {orig_t})'
                )
        if type_warnings:
            print('\n  WARNING: resource type mismatch with original test:')
            for w in type_warnings:
                print(w)
            if input('\nContinue with mismatched resource types? [y/N] ').strip().lower() != 'y':
                _offer_free()
                return

        print('\n--- New commands ---')
        if new_sting:
            print(f'\n[1] {new_sting}')
        if scripts_dir is not None:
            print(f'\n[2] (run from {scripts_dir / "scripts"}, SOL_AFW_CURRENT_LIB={scripts_dir})')
        print(f'    {new_run}')

        print('\nWhat would you like to do?')
        if new_sting:
            print('  [1] Run sting-vmr + runAutomation')
            print('  [2] Run sting-vmr only')
            print('  [3] Run runAutomation only')
            print('  [4] Exit')
            valid_choices = ('1', '2', '3', '4')
            default_choice = '4'
        else:
            print('  [1] Run runAutomation')
            print('  [2] Exit')
            valid_choices = ('1', '2')
            default_choice = '2'
        while True:
            raw = input(f'Choice [{default_choice}]: ').strip()
            if not raw:
                raw = default_choice
            if raw in valid_choices:
                choice = int(raw)
                break
            print(f'  Please enter {" or ".join(valid_choices)}.')

        if new_sting:
            run_sting = choice in (1, 2)
            run_auto  = choice in (1, 3)
            exiting   = choice == 4
        else:
            run_sting = False
            run_auto  = choice == 1
            exiting   = choice == 2

        if args.dry_run:
            print('\n(dry-run: not executing)')
            _offer_free()
            return

        if exiting:
            _offer_free()
            return

        if run_sting:
            print('\n=== Running sting-vmr ===')
            subprocess.run(shlex.split(new_sting), check=True)

        if run_auto:
            print('\n=== Running runAutomation ===')
            if scripts_dir is not None:
                e2e_dir = shlex.quote(str(scripts_dir))
                bash_cmd = (
                    f'export SOL_AFW_CURRENT_LIB={e2e_dir} && '
                    f'source "$SOL_AFW_CURRENT_LIB/envInfo/.bashrc.afw.tcllib" && '
                    f'cd {shlex.quote(str(scripts_dir / "scripts"))} && '
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
