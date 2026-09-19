"""Create a .venv and install every dependency from the offline wheelhouse.

Zero-network install for intranet build machines: uses `--no-index --find-links
offline/wheels` so pip never touches PyPI.

Usage:
    python scripts/setup_venv_offline.py                 # create/update .venv
    python scripts/setup_venv_offline.py --venv <dir>    # use a different venv
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / 'offline' / 'wheels'


def run(*args):
    return subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


def venv_python(venv):
    return venv / 'Scripts' / 'python.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', default=str(ROOT / '.venv'), help='venv directory (default: .venv)')
    parser.add_argument('--skip-optional', action='store_true', help='skip requirements-optional.txt')
    args = parser.parse_args()

    venv = Path(args.venv)
    python = venv_python(venv)

    if not WHEELHOUSE.is_dir():
        raise SystemExit(f'Missing {WHEELHOUSE}; run scripts/refresh_offline.py on a connected machine first.')

    if not python.is_file():
        print(f'Creating venv at {venv} ...')
        run(sys.executable, '-m', 'venv', str(venv))

    install = [python, '-m', 'pip', 'install', '--no-index', '--find-links', str(WHEELHOUSE)]

    run(*install, '-r', str(ROOT / 'requirements.lock.txt'))
    run(*install, 'qwen_code_sdk==0.1.0')
    if not args.skip_optional and (ROOT / 'requirements-optional.txt').is_file():
        run(*install, '-r', str(ROOT / 'requirements-optional.txt'))

    run(python, '-m', 'pip', 'check')
    print(f'Offline environment ready: {python}')


if __name__ == '__main__':
    main()
