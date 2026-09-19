"""One-command external release: produce the fully verified intranet deliverable.

Run on an internet-connected Windows machine (Python 3.13 + Node 24.13.0). Chains:

  refresh_offline -> check_offline -> archive licenses -> build -> smoke/verify
  -> package offline kit -> zip the portable app

The result is everything the intranet needs:

* build/ExcelAssistant/        pre-built, fully verified portable app — just run it;
* build/ExcelAssistant.zip     single archive of the above (primary intranet deliverable);
* build/offline-build-kit.zip  zero-network rebuild kit (future hotfixes without internet).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args):
    print(f'\n=== {script} {" ".join(args)} ===', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-refresh', action='store_true',
                        help='reuse the existing offline/ material (skip the network-heavy refresh)')
    args = parser.parse_args()

    if args.skip_refresh and not (ROOT / 'offline' / 'manifest.json').is_file():
        raise SystemExit('--skip-refresh 需要已存在的 offline/manifest.json，请先运行 refresh_offline.py')
    if not args.skip_refresh:
        run('refresh_offline.py')
    run('check_offline.py')

    run('archive_gui_licenses.py')
    run('archive_gui_licenses.py', '--cli')
    run('archive_python_licenses.py')

    run('build.py')

    run('smoke_frozen_mcp.py')
    run('smoke_frozen_environment.py')
    run('smoke_frozen_preview.py')
    run('verify_release.py')

    run('package_offline_kit.py')

    bundle = ROOT / 'build' / 'ExcelAssistant'
    if not (bundle / 'ExcelAssistant.exe').is_file():
        raise SystemExit('build/ExcelAssistant/ExcelAssistant.exe 缺失，发布未完成')
    shutil.make_archive(str(bundle), 'zip', root_dir=bundle)
    print(f'\nDone: {bundle}.zip')


if __name__ == '__main__':
    main()
