#!/usr/bin/env python3
"""Install a solcbr load (broker + solbase) onto an appliance.

Usage:
    install_load.py <load_version> <appliance>

Example:
    install_load.py 100.0main.0.6360 lab-128-38
    install_load.py 100.0main.0.6360 lab-128-38,lab-128-39
    install_load.py soltr_100.0main.0.6360 lab-128-38
"""

import argparse
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solcbr_loads import load_path, strip_soltr

SOLBASE_LOADS = Path("/home/public/RND/loads/solbase")
MSH = Path("/usr/local/devtools/bin/msh")


def find_broker_tarball(version: str) -> Path:
    load_dir = load_path(version)
    if load_dir is None:
        sys.exit(f"Error: cannot determine path for load {version!r}")
    if not load_dir.is_dir():
        sys.exit(f"Error: load directory not found: {load_dir}")
    v = strip_soltr(version)
    tarball = load_dir / "production" / f"soltr_{v}.tar.gz"
    if not tarball.exists():
        sys.exit(f"Error: broker tarball not found: {tarball}")
    return tarball


def get_solbase_version(broker_tarball: Path) -> str:
    with tarfile.open(str(broker_tarball), "r|gz") as tf:
        for member in tf:
            if member.name.endswith("manifest.txt"):
                f = tf.extractfile(member)
                if f:
                    for line in f.read().decode().splitlines()[:10]:
                        if line.startswith("solbase:"):
                            return line.split(":", 1)[1].strip()
    sys.exit(f"Error: solbase version not found in {broker_tarball}")


def find_solbase_tarball(solbase_version: str) -> Path:
    tarball = SOLBASE_LOADS / f"solbase_{solbase_version}.tar.gz"
    if not tarball.exists():
        sys.exit(f"Error: solbase tarball not found: {tarball}")
    return tarball


def setup_keyless_access(appliance: str) -> None:
    print(f"Setting up keyless SSH access to {appliance} ...")
    subprocess.run([str(MSH), appliance], input=b"exit\n")


def scp(src: Path, appliance: str, dest_dir: str) -> None:
    dest = f"root@{appliance}:{dest_dir}"
    print(f"Copying {src.name} -> {dest} ...")
    subprocess.run(["scp", str(src), dest], check=True)
    remote_path = f"{dest_dir.rstrip('/')}/{src.name}"
    subprocess.run(
        ["ssh", f"root@{appliance}", "chgrp", "solgroup", remote_path], check=True
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "load_version",
        help="Load version, e.g. 100.0main.0.6360 or soltr_100.0main.0.6360",
    )
    ap.add_argument(
        "appliances",
        help="Comma-separated appliance hostnames, e.g. lab-128-38,lab-128-39",
    )
    args = ap.parse_args()

    appliances = [a.strip() for a in args.appliances.split(",") if a.strip()]

    broker_tarball = find_broker_tarball(args.load_version)
    print(f"Broker tarball : {broker_tarball}")

    solbase_version = get_solbase_version(broker_tarball)
    print(f"Solbase version: {solbase_version}")

    solbase_tarball = find_solbase_tarball(solbase_version)
    print(f"Solbase tarball: {solbase_tarball}")

    for appliance in appliances:
        print(f"\n--- {appliance} ---")
        setup_keyless_access(appliance)
        scp(solbase_tarball, appliance, "/usr/sw/jail/loads/")
        scp(broker_tarball, appliance, "/usr/sw/jail/loads/")

    print("\nDone.")


if __name__ == "__main__":
    main()
