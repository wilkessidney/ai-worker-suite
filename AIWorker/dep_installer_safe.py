"""
check_install_packages.py

Simple script that hardcodes the project's required packages and ensures they are installed
before running the server or tests. It will install missing packages (or upgrade if below
required version) by invoking pip via the running Python interpreter.

Usage: python check_install_packages.py

This script is intentionally conservative: it uses the distribution/package names from
`requirements.txt` and calls pip to install the exact spec (e.g. "requests>=2.31.0").
It prints a concise summary at the end.
"""

from __future__ import annotations
import sys
import subprocess
import importlib
import importlib.metadata
import re
from typing import List, Tuple, Optional
import io

# try set gbk problem
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    elif hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# Hardcoded package requirements (merged from workspace requirements)
# Note: versions intentionally relaxed (no strict pins).
REQUIRED_PACKAGES: List[str] = [
    "fastmcp",
    "requests",
    "pandas",
    "numpy",
    "tqdm",
    "selenium",
    "beautifulsoup4",
    "pydantic",
    "email-validator",
    "aiohttp",
    "webdriver-manager",
    "playwright",
    "openai",
    "flask",
    "flask-cors",
    "werkzeug",
    "wqb",
    "jupyter",
    "notebook",
    "ipykernel",
    "PyPDF2",
    "pdfplumber",
    "PyMuPDF",
    "python-docx",
    "docx2txt",
    "striprtf",
    "lxml",
    "cozepy",
    "ply",
    "Pillow",
    "fastembed",
    "chromadb",
    "watchdog",
    "pypdf"
]


def parse_spec(spec: str) -> Tuple[str, Optional[str]]:
    """Return (name, min_version) for a spec like 'pkg>=1.2.3'."""
    if ">=" in spec:
        name, ver = spec.split(">=", 1)
        return name.strip(), ver.strip()
    return spec.strip(), None


def version_tuple(v: str) -> List[int]:
    parts = re.split(r"[^0-9]+", v)
    nums = []
    for p in parts:
        if p == "":
            continue
        try:
            nums.append(int(p))
        except ValueError:
            # Non-numeric part, stop parsing further
            break
    return nums


def is_version_sufficient(installed: str, required: str) -> bool:
    if not installed:
        return False
    try:
        i_parts = version_tuple(installed)
        r_parts = version_tuple(required)
        # Compare element-wise
        for a, b in zip(i_parts, r_parts):
            if a > b:
                return True
            if a < b:
                return False
        # If equal up to the length of required, installed is sufficient if it's at least as long
        return len(i_parts) >= len(r_parts)
    except Exception:
        return False


def install_package(spec: str) -> Tuple[bool, str]:
    """Install a package spec using pip. Retries with --break-system-packages if needed (PEP 668)."""
    
    def run_pip(extra_args=None):
        cmd = [sys.executable, "-m", "pip", "install", "-v", spec]
        if extra_args:
            cmd.extend(extra_args)
            
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output_lines = []
            if proc.stdout:
                for line in proc.stdout:
                    output_lines.append(line)
                    try:
                        print(line.rstrip())
                    except Exception:
                        pass
            proc.wait()
            out = "".join(output_lines)
            success = proc.returncode == 0
            return success, out
        except Exception as e:
            return False, str(e)

    # First Attempt
    success, out = run_pip()
    
    # Retry logic for PEP 668 (Common on Mac Homebrew / Debian 12+)
    if not success and "externally-managed-environment" in out:
        print(f"\n⚠️  Standard install failed due to PEP 668. Retrying {spec} with --break-system-packages...")
        success, out = run_pip(["--break-system-packages"])

    return success, out


def main():
    results = []
    print("Checking required packages...\n")
    for spec in REQUIRED_PACKAGES:
        name, min_ver = parse_spec(spec)
        installed_ver = None
        try:
            installed_ver = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed_ver = None
        except Exception:
            # Some packages may have different distribution vs import names; try best-effort
            installed_ver = None

        needs_install = False
        action = "present"
        if installed_ver is None:
            needs_install = True
            action = "install"
        elif min_ver is not None:
            if not is_version_sufficient(installed_ver, min_ver):
                needs_install = True
                action = f"upgrade (installed {installed_ver} < required {min_ver})"

        if needs_install:
            print(f"-> {name}: {action} via pip ({spec})")
            success, output = install_package(spec)
            # Attempt to read installed version after install
            installed_after = None
            if success:
                try:
                    installed_after = importlib.metadata.version(name)
                except Exception:
                    installed_after = None
                if installed_after:
                    print(f"   -> {name} now installed as: {installed_after}")

            results.append({
                "name": name,
                "spec": spec,
                "installed_version_before": installed_ver,
                "installed_version_after": installed_after,
                "action": action,
                "success": success,
                "output": output
            })
        else:
            print(f"-> {name}: OK (installed: {installed_ver})")
            results.append({
                "name": name,
                "spec": spec,
                "installed_version_before": installed_ver,
                "action": "none",
                "success": True,
                "output": ""
            })

    # Summary
    print("\nSummary:")
    installed_count = sum(1 for r in results if r["success"] and r["action"] == "none")
    installed_or_fixed = sum(1 for r in results if r["success"] and r["action"] != "none")
    failed = [r for r in results if not r["success"]]

    print(f"  Packages already OK: {installed_count}")
    print(f"  Packages installed/upgraded by this script: {installed_or_fixed}")
    print(f"  Packages failed to install: {len(failed)}")
    if failed:
        for f in failed:
            print(f"    - {f['name']}: attempted '{f['spec']}' -> error (see details below)")

    # If any failed, print their outputs for debugging
    if failed:
        print("\nFailed install details:\n")
        for f in failed:
            print("-----")
            print(f"Package: {f['name']}")
            print(f"Spec: {f['spec']}")
            print(f"Installed before: {f.get('installed_version_before')}")
            print(f"Installed after: {f.get('installed_version_after')}")
            print("Output:")
            print(f.get("output", "(no output)"))

    print("\nDone.")
    # Exit with non-zero code if any install failed
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
