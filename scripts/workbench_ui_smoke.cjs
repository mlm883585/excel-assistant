// Use PLAYWRIGHT_MODULE to point at an existing local Playwright installation.
const { createHarness, expect } = require('./ui_harness.cjs');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const { page, server, errors, close } = await createHarness({ viewport: { width: 1366, height: 768 } });
  const timings = [], largePages = [];
  try {
    await page.goto(`http://127.0.0.1:${server.port}`);
    await page.getByRole('navigation', {name:'任务导航'}).getByRole('button', {name:/^库存.csv/}).click();
    await page.getByText('共 400 行', { exact: false }).waitFor({ timeout: 30000 });
    if (server.large_benchmark) {
      await page.getByRole('button', {name:/^synthetic-0.xlsx/}).click();
      await page.getByText('共 100,000 行', { exact:false }).waitFor({timeout:90000});
      for (let i = 0; i < 50; i++) {
        const start = performance.now();
        await page.getByRole('button', {name:'下一页',exact:true}).click();
        await page.waitForFunction(code => document.querySelector('.data-grid')?.textContent.includes(code), String((i+1)*50).padStart(8,'0'));
        largePages.push(performance.now()-start);
      }
      await page.getByRole('navigation', {name:'任务导航'}).getByRole('button', {name:/^库存.csv/}).click();
      await page.getByText('共 400 行', {exact:false}).waitFor();
    }
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await page.locator('.history').count(), 30);
    await page.screenshot({ path: 'build/workbench-ui.png', fullPage: true, animations: 'disabled' });
    await page.getByRole('button', {name:/^宽表.csv/}).click();
    await page.getByText('共 400 行', { exact: false }).waitFor({ timeout: 30000 });
    await page.locator('.el-table-v2__header-cell').first().waitFor();
    assert.ok(await page.locator('.el-table-v2__header-cell').count() < 30, 'wide table must virtualize columns');
    await page.locator('.data-grid').hover();
    await page.mouse.wheel(48000, 0);
    await page.getByText('字段299', { exact:true }).waitFor({timeout:10000});
    assert.ok(await page.locator('.el-table-v2__header-cell').count() < 30);
    await page.getByRole('navigation', {name:'任务导航'}).getByRole('button', {name:/^库存.csv/}).click();
    await page.getByText('共 400 行', { exact: false }).waitFor({ timeout: 30000 });
    for (let i = 0; i < 5; i++) {
      const start = Date.now();
      await page.getByRole('button', { name: '下一页', exact: true }).click();
      await page.waitForFunction(expected => document.querySelector('.page-label')?.textContent === String(expected), i + 2);
      timings.push(Date.now() - start);
    }
    await page.getByRole('tab', { name: '用文字描述', exact: true }).click();
    assert.ok(await page.locator('.message').count() <= 200);
    await page.getByRole('button', { name: '更早的消息', exact: true }).click();
    await page.getByRole('button', { name: '返回最新消息', exact: true }).waitFor();
    assert.ok(await page.locator('.message').count() <= 200);
    await page.getByRole('tab', { name: '常用操作', exact: true }).click();
    await page.getByRole('button', { name: '开始处理', exact: true }).click();
    await page.getByText('输出行数', { exact: true }).waitFor({ timeout: 30000 });
    await page.getByText('共 800 行', { exact: false }).waitFor({ timeout: 30000 });
    assert.equal(await page.locator('.metrics strong').filter({ hasText: /^800$/ }).count(), 1);
    await page.screenshot({ path: 'build/workbench-result.png', fullPage: true, animations: 'disabled' });
    // Deterministic clock advancement checks that terminal tasks schedule no new polls.
    await page.clock.install();
    const before = await page.evaluate(() => window.rpcStats.filter(x => x.method === 'tasks.get').length);
    await page.clock.fastForward(10000);
    const after = await page.evaluate(() => window.rpcStats.filter(x => x.method === 'tasks.get').length);
    assert.equal(after, before);
    for (const viewport of [{ width: 1920, height: 1080 }, { width: 1093, height: 614 }, { width: 911, height: 512 }]) {
      await page.setViewportSize(viewport);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.getByRole('button', { name: '用 Excel 打开', exact: true }).scrollIntoViewIfNeeded();
    }
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.getByRole('button', { name: '设置与环境', exact: false }).click();
    await page.getByRole('tab', { name: '高级诊断', exact: true }).waitFor();
    await page.getByRole('tab', { name: '模型连接', exact: true }).click();
    await page.getByRole('textbox', { name: '模型服务地址', exact: true }).waitFor();
    assert.equal(errors.length, 0, errors.join('\n'));
    assert.ok(Math.max(...timings) <= 200, 'Ordinary page interactions must be <= 200 ms');
    assert.equal(largePages.length, 50, 'Run the 100,000-row benchmark before this suite');
    assert.ok(largePages.sort((a,b)=>a-b)[47] <= 500, 'Cached page end-to-end P95 must be <= 500 ms');
    const rpc = await page.evaluate(() => window.rpcStats);
    fs.writeFileSync('build/workbench-ui-metrics.json', JSON.stringify({ errors, interaction_ms: timings, large_xlsx_pages: largePages.length, large_xlsx_page_e2e_p95_ms: largePages.sort((a,b)=>a-b)[47], cached_page_rpc_ms: rpc.filter(x => x.method === 'files.preview_page').map(x => x.ms), terminal_polling_stopped: true, rendered_history_limit: 30, rendered_message_limit: 200, virtualized_columns: 300 }, null, 2));
    console.log('WORKBENCH_UI_REAL_RPC_OK');
  } catch (error) {
    if (page) { await page.screenshot({path:'build/workbench-failure.png',fullPage:true,animations:'disabled'}); console.log(await page.locator('main').innerText()); console.log(errors); }
    throw error;
  } finally { await close(); }
})().catch(error => { console.error(error); process.exit(1); });
