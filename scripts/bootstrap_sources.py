"""Fetch pinned upstream sources, preserving licenses; never overwrites files."""
import io
import json
import re
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

PPX_EXCLUDED = ('ppx/assets', 'ppx/packages/ppx-py/src/ppx_py/template/assets')


def clean_ppx_readme(text):
    """Remove promotional artwork, retaining the technical docs and license notice."""
    text = re.sub(r'^<p align="center"><img[^\n]+</p>\s*', '', text)
    start, end = text.find('## 支持 PPX'), text.find('## 开源协议')
    if start >= 0 and end > start:
        text = text[:start] + text[end:]
    return text


def fetch(repo, revision, selections, *, exclude=(), clean_readmes=False):
    url = f'https://codeload.github.com/{repo}/zip/{revision}'
    with urllib.request.urlopen(url) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    for item in archive.infolist():
        relative = '/'.join(item.filename.split('/')[1:])
        if item.is_dir():
            continue
        if any(relative == prefix or relative.startswith(prefix + '/') for prefix in exclude):
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
                content = archive.read(item)
                if clean_readmes and output.name == 'README.md':
                    content = clean_ppx_readme(content.decode('utf-8')).encode('utf-8')
                output.write_bytes(content)

if __name__ == '__main__':
    fetch('pangao1990/PPX', '247da805d531910302fc9505b96aa3218cd952b9', [
        ('ppx/packages/ppx-py', 'vendor/ppx-py'),
        ('ppx/packages/ppx-js', 'vendor/ppx-js'),
        ('LICENSE', 'LICENSE')], exclude=PPX_EXCLUDED, clean_readmes=True)
    request = urllib.request.Request('https://api.github.com/repos/QwenLM/qwen-code/commits/main', headers={'User-Agent': 'excel-assistant-build'})
    pin = ROOT / 'vendor/qwen-code-revision.txt'
    revision = pin.read_text().strip() if pin.exists() else json.load(urllib.request.urlopen(request))['sha']
    fetch('QwenLM/qwen-code', revision, [('packages/sdk-python', 'vendor/qwen-code-sdk'), ('LICENSE', 'vendor/QWEN-LICENSE')])
    pin.write_text(revision + '\n')
