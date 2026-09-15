"""Explicit --smoke diagnostics for the real window; not used by normal startup."""
import json
from pathlib import Path
import time


def check_window(window, icon_path: Path, output: Path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        loaded = window.evaluate_js("Boolean(document.querySelector('.brand img')?.complete && document.querySelector('.brand img')?.naturalWidth)")
        if loaded:
            break
        time.sleep(.1)
    else:
        raise RuntimeError('品牌图标未载入')
    assert window.evaluate_js('document.title') == 'Excel 数据助手'
    resources = window.evaluate_js("performance.getEntriesByType('resource').map(r=>r.name)")
    assert not any(url.startswith(('http://', 'https://')) and not url.startswith(
        ('http://127.0.0.1:', 'http://localhost:')) for url in resources), resources

    from System import Action
    from System.Drawing import Icon, Size
    result = {}

    def native_check():
        try:
            form = window.native
            assert form.Text == 'Excel 数据助手', form.Text
            assert form.ShowInTaskbar
            bitmap = form.Icon.ToBitmap()
            expected_icon = Icon(str(icon_path), Size(bitmap.Width, bitmap.Height))
            expected = expected_icon.ToBitmap()
            try:
                for x in range(bitmap.Width):
                    for y in range(bitmap.Height):
                        assert bitmap.GetPixel(x, y).ToArgb() == expected.GetPixel(x, y).ToArgb()
                result.update(native_icon=True, native_title=str(form.Text), taskbar_window=True)
            finally:
                bitmap.Dispose()
                expected.Dispose()
                expected_icon.Dispose()
        except BaseException as error:
            result['error'] = repr(error)

    window.native.Invoke(Action(native_check))
    if 'error' in result:
        raise RuntimeError(result['error'])
    result.update(passed=True, renderer='edgechromium', external_requests=0)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
