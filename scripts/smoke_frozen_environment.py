"""Exercise the frozen diagnostic worker and bundled CLI/Node without customer services."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from assistant.diagnostic_process import run_probe


def main():
    bundle = ROOT / 'build/ExcelAssistant'
    exe = bundle / 'ExcelAssistant.exe'
    if not exe.is_file():
        raise RuntimeError('Build the portable application first')
    config = {'cli': str(bundle / 'node_modules/@qwen-code/qwen-code/cli.js'),
              'node_executable': str(bundle / 'runtime/node.exe')}
    with patch.object(sys, 'executable', str(exe)), patch.object(sys, 'frozen', True, create=True):
        for kind, timeout in [('dependencies', 20), ('agent', 90)]:
            result = run_probe(kind, config if kind == 'agent' else None, timeout=timeout)
            if result['status'] != 'pass':
                raise RuntimeError(f'Frozen {kind} failed: {result}')
            print(f'FROZEN_{kind.upper()}_OK', flush=True)


if __name__ == '__main__':
    main()
