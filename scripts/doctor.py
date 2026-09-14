"""Local deployment diagnostics; never installs software or contacts a model by default."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant.diagnostics import local_check, export_report
from assistant.runtime import RuntimeManager
from assistant.store import data_root


def main():
    parser = argparse.ArgumentParser(description='Excel 助手本地环境检测')
    parser.add_argument('--quick', action='store_true', help='只检查本地启动条件，不启动组件检测进程')
    args = parser.parse_args()
    value = local_check(RuntimeManager(data_root()), deep=not args.quick)
    safe, _ = export_report(value)
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 1 if value['status'] == 'fail' else 0


if __name__ == '__main__':
    sys.exit(main())
