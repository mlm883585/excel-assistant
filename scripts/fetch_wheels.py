"""Download every Python wheel into the offline wheelhouse (offline/wheels/).

Run on an internet-connected Windows machine with Python 3.13 (the same
interpreter the app builds with). Produces wheels for:

1. requirements.lock.txt     — frozen runtime closure, binary-only wheels;
2. requirements-optional.txt — future/optional packages + transitive closure;
3. vendor/qwen-code-sdk      — built into a wheel so the intranet never needs
                               a build backend (hatchling) at install time.

The result is consumed by setup_venv_offline.py with `pip install --no-index`.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / 'offline' / 'wheels'


def pip(*args):
    return subprocess.run([sys.executable, '-m', 'pip', *args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-optional', action='store_true', help='skip requirements-optional.txt')
    parser.add_argument('--skip-sdk', action='store_true', help='skip building the qwen-code-sdk wheel')
    args = parser.parse_args()

    WHEELHOUSE.mkdir(parents=True, exist_ok=True)

    # 1. Frozen runtime closure — download prebuilt wheels and build the rare
    #    source-only pure-Python package (e.g. proxy_tools) into a wheel, so the
    #    intranet installs from wheels only and never compiles.
    pip('wheel', '-r', str(ROOT / 'requirements.lock.txt'),
        '--wheel-dir', str(WHEELHOUSE))

    # 2. Optional/future packages with their transitive closure.
    if not args.skip_optional:
        optional = ROOT / 'requirements-optional.txt'
        if optional.is_file():
            pip('wheel', '-r', str(optional), '--wheel-dir', str(WHEELHOUSE))

    # 3. Local SDK -> wheel (build isolation fetches hatchling on the connected machine).
    if not args.skip_sdk:
        pip('wheel', str(ROOT / 'vendor' / 'qwen-code-sdk'),
            '--wheel-dir', str(WHEELHOUSE), '--no-deps')

    print(f'Wheels ready in {WHEELHOUSE}')


if __name__ == '__main__':
    main()
