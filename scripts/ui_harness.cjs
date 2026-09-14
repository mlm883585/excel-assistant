// Each UI suite owns an isolated synthetic backend and closes its workers on exit.
const { chromium, expect } = require(process.env.PLAYWRIGHT_MODULE || 'playwright/test');
const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');
const root = path.resolve(__dirname, '..');

async function createHarness({ viewport = { width: 1600, height: 1000 } } = {}) {
  const worker = spawn(process.env.UI_PYTHON || path.join(root, '.venv/Scripts/python.exe'),
    ['-X', 'utf8', path.join(__dirname, 'workbench_ui_server.py')],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '';
  worker.stderr.on('data', chunk => { stderr += chunk; });
  const exited = new Promise(resolve => worker.once('exit', resolve));
  let browser;
  try {
    const server = await new Promise((resolve, reject) => {
      const lines = readline.createInterface({ input: worker.stdout });
      const deadline = setTimeout(() => { worker.kill(); reject(new Error('Synthetic backend startup timed out')); }, 30000);
      worker.once('error', reject);
      worker.once('exit', code => { clearTimeout(deadline); reject(new Error(`Synthetic backend exited ${code}: ${stderr}`)); });
      lines.on('line', line => {
        if (!line.startsWith('UI_SERVER_READY ')) return;
        clearTimeout(deadline);
        resolve(JSON.parse(line.slice('UI_SERVER_READY '.length)));
      });
    });
    browser = await chromium.launch({
      executablePath: process.env.CHROME_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    });
    const page = await browser.newPage({ viewport });
    page.setDefaultTimeout(15000);
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => {
      if (!request.url().startsWith('http://127.0.0.1:') && !request.url().startsWith('data:')) external.push(request.url());
    });
    await page.addInitScript(() => {
      window.rpcStats = [];
      window.pywebview = { api: { call: async (...args) => {
        const started = performance.now();
        const response = await fetch('/__rpc', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
        });
        const result = await response.json();
        window.rpcStats.push({ method: args[0], ms: performance.now() - started });
        return result;
      } } };
    });
    const url = `http://127.0.0.1:${server.port}`;
    const rpc = async (method, params = {}) => {
      const response = await page.request.post(`${url}/__rpc`, { data: [method, params] });
      const result = await response.json();
      if (result.ok === false || result.error) throw new Error(JSON.stringify(result));
      return result.data ?? result.result ?? result;
    };
    const close = async () => {
      try {
        await page.request.post(`${url}/__shutdown`, { data: { token: server.shutdown_token } });
      } finally {
        await browser.close();
        const deadline = setTimeout(() => worker.kill(), 10000);
        const code = await exited;
        clearTimeout(deadline);
        if (code !== 0) throw new Error(`Synthetic backend did not shut down cleanly: ${code}\n${stderr}`);
      }
    };
    return { browser, page, server, url, rpc, errors, external, close };
  } catch (error) {
    await browser?.close();
    worker.kill();
    throw error;
  }
}
module.exports = { createHarness, expect };
