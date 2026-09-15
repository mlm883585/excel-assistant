"""Check shipped branding, including the actual icon resources embedded in the EXE."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.source_archive import source_files

OLD_IMAGE_HASHES = {
    '19f293fe2eaf364a015cc9da1b86847f2e92d0e6b619e54e913d105855acdd4d',
    '01fabc5586a7a939e18204c9850e2cfb2a68a9a3bbcdfb36a9986f3f6b0c75c7',
    '984333026448b233f6288ccb6e59809719837acd25a5751f42a5cfb745496cfe',
    'd2c98b957ad00271a33ff72f871014823f26ca119ec01f75b059a16192484f87',
}
SIZES = {16, 24, 32, 48, 64, 128, 256}


def verify_branding(root=ROOT, bundle=None):
    from PIL import Image
    root = Path(root)
    assets = root / 'assets/branding'
    with Image.open(assets / 'logo.png') as png:
        if png.size != (1024, 1024) or png.mode != 'RGBA' or png.getpixel((0, 0))[3] != 0:
            raise ValueError('主图尺寸或透明边缘不正确')
    with Image.open(assets / 'logo.ico') as ico:
        if ico.ico.sizes() != {(size, size) for size in SIZES}:
            raise ValueError('ICO 缺少约定尺寸')

    for path in source_files(root):
        if path.suffix.lower() in {'.png', '.ico', '.icns'}:
            if hashlib.sha256(path.read_bytes()).hexdigest() in OLD_IMAGE_HASHES:
                raise ValueError(f'源码仍包含上游品牌图片：{path.relative_to(root)}')
    for package in ('ppx-py', 'ppx-js'):
        readme = (root / 'vendor' / package / 'README.md').read_text(encoding='utf-8')
        if '<img' in readme or '## 支持 PPX' in readme or '## 关注公众号' in readme:
            raise ValueError(f'{package} 仍包含宣传素材')
        if '开源协议' not in readme or not (root / 'vendor' / package / 'LICENSE').is_file():
            raise ValueError(f'{package} 缺少许可证说明')

    for name in ('logo.svg', 'logo.png', 'logo.ico'):
        expected = (assets / name).read_bytes()
        if (root / 'gui/dist/branding' / name).read_bytes() != expected:
            raise ValueError(f'前端品牌素材不是当前版本：{name}')
    result = {'passed': True, 'ico_sizes': sorted(SIZES), 'old_images': 0}
    if bundle is not None:
        import pefile
        bundle = Path(bundle)
        if any((bundle / name).exists() for name in ('PPX-README.md', 'PPX-LICENSE')):
            raise ValueError('便携包仍包含旧的根目录品牌资料')
        for path in bundle.rglob('*'):
            if path.is_file() and path.suffix.lower() in {'.png', '.ico', '.icns'}:
                if hashlib.sha256(path.read_bytes()).hexdigest() in OLD_IMAGE_HASHES:
                    raise ValueError(f'便携包仍包含上游品牌图片：{path.relative_to(bundle)}')
        if (bundle / 'licenses/ppx/LICENSE').read_bytes() != (root / 'vendor/ppx-py/LICENSE').read_bytes():
            raise ValueError('随包 PPX 许可证缺失或不一致')
        expected = (assets / 'logo.ico').read_bytes()
        if (bundle / '_internal/assets/branding/logo.ico').read_bytes() != expected:
            raise ValueError('窗口图标不是当前版本')
        images = []
        count = struct.unpack_from('<H', expected, 4)[0]
        for index in range(count):
            length, offset = struct.unpack_from('<II', expected, 6 + index * 16 + 8)
            images.append(expected[offset:offset + length])
        with pefile.PE(str(bundle / 'ExcelAssistant.exe')) as pe:
            resources = []
            for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
                if kind.id == pefile.RESOURCE_TYPE['RT_ICON']:
                    for entry in kind.directory.entries:
                        for language in entry.directory.entries:
                            data = language.data.struct
                            resources.append(pe.get_data(data.OffsetToData, data.Size))
            if not all(image in resources for image in images):
                raise ValueError('EXE 中的图标资源与当前 ICO 不一致')
        result['exe_icon_sizes'] = count
    return result


if __name__ == '__main__':
    bundle = ROOT / 'build/ExcelAssistant' if '--bundle' in sys.argv else None
    print(json.dumps(verify_branding(bundle=bundle)))
