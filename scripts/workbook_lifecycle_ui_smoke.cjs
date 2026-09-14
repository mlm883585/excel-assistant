const { createHarness, expect } = require('./ui_harness.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

(async () => {
  const { page, rpc, server, url, errors, close } = await createHarness();
  const checks = [];
  const navigation = page.getByRole('navigation', { name: '任务导航' });
  const inventory = navigation.getByRole('button', { name: /^库存.csv/ });
  const wide = navigation.getByRole('button', { name: /^宽表.csv/ });
  try {
    await page.goto(url);
    await inventory.click();
    // Complete the old request after a different task has already become current.
    const opened = deferred(), release = deferred(), completed = deferred();
    await page.route('**/__rpc', async route => {
      const [method] = route.request().postDataJSON();
      if (method !== 'workbooks.open') return route.continue();
      const response = await route.fetch();
      opened.resolve();
      await release.promise;
      await route.fulfill({ response });
      completed.resolve();
    });
    await page.getByRole('button', { name: '在表格编辑器中打开', exact: true }).click();
    await opened.promise;
    await wide.click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('宽表.csv');
    release.resolve();
    await completed.promise;
    await page.unroute('**/__rpc');
    await expect(page.locator('.univer-container')).toHaveCount(0);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('宽表.csv');
    checks.push('late_workbook_response_ignored');

    await inventory.click();
    const requested = deferred(), releaseTask = deferred(), completedTask = deferred();
    await page.route('**/__rpc', async route => {
      const [method, params] = route.request().postDataJSON();
      if (method !== 'tasks.get' || params.task_id === server.task_id || params.after !== Number.MAX_SAFE_INTEGER) return route.continue();
      const response = await route.fetch();
      requested.resolve();
      await releaseTask.promise;
      await route.fulfill({ response });
      completedTask.resolve();
    });
    await wide.click();
    await requested.promise;
    await inventory.click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('库存.csv');
    releaseTask.resolve();
    await completedTask.promise;
    await page.unroute('**/__rpc');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('库存.csv');
    checks.push('late_task_response_ignored');

    await page.getByRole('button', { name: '在表格编辑器中打开', exact: true }).click();
    await expect(page.locator('.save-state')).toContainText('已保存');
    const nameBox = page.locator('.univer-container input.univer-appearance-none');
    await expect(nameBox).toHaveValue('A1');
    let saveFailures = 0;
    await page.route('**/__rpc', async route => {
      const [method] = route.request().postDataJSON();
      if (method !== 'workbooks.save') return route.continue();
      ++saveFailures;
      await route.fulfill({ json: { ok: false, error: { code: 'TEST_SAVE_FAILURE', message: '模拟保存失败' } } });
    });
    await nameBox.fill('F1');
    await nameBox.press('Enter');
    await page.keyboard.insertText('需要保留的修改');
    await page.keyboard.press('Enter');
    await expect(page.locator('.workbook-panel .el-alert')).toContainText('模拟保存失败');
    await wide.click();
    await expect.poll(() => saveFailures).toBeGreaterThanOrEqual(2);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('库存.csv');
    await expect(page.locator('.save-state')).toContainText('未保存');
    await page.unroute('**/__rpc');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.locator('.save-state')).toContainText('已保存');
    const books = await rpc('workbooks.list', { task_id: server.task_id });
    const record = await rpc('workbooks.open', { task_id: server.task_id, workbook_id: books[0].id });
    assert.equal(record.snapshot.sheets[0].cells['0,5'].value, '需要保留的修改');
    checks.push('save_failure_blocks_navigation_and_recovers');

    let exports = 0;
    await page.route('**/__rpc', async route => {
      const [method] = route.request().postDataJSON();
      if (method !== 'outputs.export') return route.continue();
      ++exports;
      await route.fulfill({ json: { ok: true, data: { exported: false } } });
    });
    await page.getByRole('button', { name: '确认并导出', exact: true }).click();
    await expect.poll(() => exports).toBe(1);
    await expect(page.locator('.el-message--success')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '确认并导出', exact: true })).toBeEnabled();
    await page.unroute('**/__rpc');
    checks.push('cancelled_export_does_not_report_success');

    // Repeated disposal must leave only the active view and bounded history nodes.
    const cdp = await page.context().newCDPSession(page), heapSamples = [];
    for (let i = 0; i < 8; i++) {
      await wide.click();
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('宽表.csv');
      await inventory.click();
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('库存.csv');
      await page.getByRole('button', { name: '在表格编辑器中打开', exact: true }).click();
      await expect(page.locator('.save-state')).toContainText('已保存');
      await wide.click();
      await expect(page.locator('.univer-container')).toHaveCount(0);
      await cdp.send('HeapProfiler.collectGarbage');
      heapSamples.push(Math.round((await cdp.send('Runtime.getHeapUsage')).usedSize / 1024 ** 2));
    }
    assert.ok(Math.max(...heapSamples.slice(-3)) <= Math.max(...heapSamples.slice(0,3)) + 12,
      `Repeated editor disposal retained growing JS heap: ${heapSamples}`);
    await expect(page.locator('.univer-container')).toHaveCount(0);
    assert.ok(await navigation.locator('.history').count() <= 30);
    assert.deepEqual(errors, []);
    checks.push('repeated_switch_disposes_editor');
    fs.writeFileSync('build/workbook-lifecycle-result.json', JSON.stringify({ passed: true, checks, heap_mb_after_disposal: heapSamples }, null, 2));
    console.log('LIFECYCLE_CHECKS_OK', checks.join(', '));
  } finally {
    await page.screenshot({ path: 'build/workbook-lifecycle-latest.png', fullPage: true }).catch(() => {});
    await close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
