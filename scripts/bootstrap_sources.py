"""Fetch pinned upstream sources, preserving licenses; never overwrites files."""
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def fetch(repo, revision, selections):
    url = f'https://codeload.github.com/{repo}/zip/{revision}'
    with urllib.request.urlopen(url) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    for item in archive.infolist():
        relative = '/'.join(item.filename.split('/')[1:])
        if item.is_dir():
            continue
        for prefix, destination in selections:
            if relative == prefix or relative.startswith(prefix + '/'):
                suffix = relative[len(prefix):].lstrip('/')
                output = ROOT / destination / suffix if suffix else ROOT / destination
                if not output.resolve().is_relative_to(ROOT):
                    raise ValueError('Unsafe archive path')
                if output.exists():
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(item))

if __name__ == '__main__':
    fetch('pangao1990/PPX', '247da805d531910302fc9505b96aa3218cd952b9', [
        ('ppx/packages/ppx-py', 'vendor/ppx-py'),
        ('ppx/packages/ppx-js', 'vendor/ppx-js'),
        ('ppx/assets', 'ppx/assets'), ('LICENSE', 'LICENSE')])
    request = urllib.request.Request('https://api.github.com/repos/QwenLM/qwen-code/commits/main', headers={'User-Agent': 'excel-assistant-build'})
    pin = ROOT / 'vendor/qwen-code-revision.txt'
    revision = pin.read_text().strip() if pin.exists() else json.load(urllib.request.urlopen(request))['sha']
    fetch('QwenLM/qwen-code', revision, [('packages/sdk-python', 'vendor/qwen-code-sdk'), ('LICENSE', 'vendor/QWEN-LICENSE')])
    pin.write_text(revision + '\n')
