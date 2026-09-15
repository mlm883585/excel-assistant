// Render the original SVG using local Chromium; no network or extra runtime dependency.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright/test');
const { spawnSync } = require('node:child_process');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
    await page.route('**/*', route => route.abort());
    const svg = readFileSync(path.join(root, 'assets/branding/logo.svg'), 'utf8');
    await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block}</style>${svg}`);
    await page.locator('svg').screenshot({ path: path.join(root, 'assets/branding/logo.png'), omitBackground: true });
  } finally {
    await browser.close();
  }
  const result = spawnSync(process.env.UI_PYTHON || path.join(root, '.venv/Scripts/python.exe'), ['-c',
    "from PIL import Image; from pathlib import Path; p=Path('assets/branding'); Image.open(p/'logo.png').save(p/'logo.ico', sizes=[(n,n) for n in (16,24,32,48,64,128,256)])"],
    { cwd: root, windowsHide: true, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`ICO generation failed: ${result.status}`);
  console.log('BRANDING_RENDERED');
})().catch(error => { console.error(error); process.exitCode = 1; });
