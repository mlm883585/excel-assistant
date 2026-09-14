// Synthetic local UI test. Uses an existing Playwright installation and local Chrome.
const { createHarness, expect } = require('./ui_harness.cjs');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const { page, server, rpc, errors, external, close } = await createHarness();
  try {
    await page.goto(`http://127.0.0.1:${server.port}`);
    await page.getByRole('button', {name:/^库存.csv/}).click();
    await page.getByRole('button', {name:'在表格编辑器中打开',exact:true}).click();
    await expect(page.locator('.univer-container canvas').first()).toBeVisible({timeout:30000});
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    await page.waitForFunction(() => [...document.querySelectorAll('.univer-container input')].some(n => n.value==='A1'), {timeout:15000});
    await expect(page.getByRole('dialog')).toHaveCount(0);
    // Univer's canvas has no cell DOM nodes. Its visible name box locates cells exactly.
    const nameBox = page.locator('.univer-container input.univer-appearance-none');
    async function writeCell(address,text) {
      await nameBox.fill(address); await nameBox.press('Enter');
      await page.keyboard.insertText(text); await page.keyboard.press('Enter');
    }
    await writeCell('D1','金额');
    await writeCell('C2','1'); await writeCell('C3','2'); await writeCell('C4','3');
    await writeCell('D2','=SUM(C2:C4)');
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    const all = await rpc('workbooks.list',{task_id:server.task_id});
    fs.writeFileSync('build/workbook-ui-rpc.json',JSON.stringify(all,null,2));
    const current = await rpc('workbooks.open',{task_id:server.task_id,workbook_id:all[0].id});
    assert.equal(current.snapshot.sheets[0].cells['0,3'].value,'金额');
    assert.equal(current.snapshot.sheets[0].cells['1,3'].formula,'=SUM(C2:C4)');
    assert.equal(current.snapshot.sheets[0].cells['1,3'].value,6);
    // Exercise the OS clipboard and find/replace through the actual editor controls.
    await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:`http://127.0.0.1:${server.port}`});
    await writeCell('F1','待复制');
    await nameBox.fill('F1');await nameBox.press('Enter');await page.keyboard.press('Control+c');
    await nameBox.fill('G1');await nameBox.press('Enter');await page.keyboard.press('Control+v');
    const cell = async key => (await rpc('workbooks.open',{task_id:server.task_id,workbook_id:current.snapshot.id})).snapshot.sheets[0].cells[key]?.value;
    await expect.poll(()=>cell('0,6'),{timeout:30000}).toBe('待复制');
    await page.keyboard.press('Control+z');await expect.poll(()=>cell('0,6'),{timeout:30000}).toBeUndefined();
    await page.keyboard.press('Control+y');await expect.poll(()=>cell('0,6'),{timeout:30000}).toBe('待复制');
    console.log('CLIPBOARD_UNDO_REDO_OK');
    await page.keyboard.press('Control+h');
    await page.getByPlaceholder('输入查找内容',{exact:true}).fill('待复制');
    await page.getByPlaceholder('输入查找内容',{exact:true}).press('Enter');
    await page.getByPlaceholder('输入替换内容',{exact:true}).fill('已替换');
    await page.getByRole('button',{name:'替换全部',exact:true}).click();
    await page.getByRole('button',{name:'确定',exact:true}).click();
    await expect.poll(()=>cell('0,6'),{timeout:30000}).toBe('已替换');
    assert.equal(await cell('0,5'),'已替换');
    console.log('FIND_REPLACE_OK');
    await page.keyboard.press('Escape');
    // Viewing an old revision must be read-only; restore produces a new revision.
    await page.getByRole('button',{name:'历史版本',exact:true}).click();
    await page.getByRole('dialog').getByRole('button',{name:'查看',exact:true}).last().click();
    await expect(page.locator('.save-state')).toContainText('只读查看',{timeout:30000});
    await expect(page.getByRole('button',{name:'开始处理',exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'返回当前版本',exact:true}).click();
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    await writeCell('J1','=J1');
    await expect.poll(()=>cell('0,9'),{timeout:30000}).toBe('#CYCLE!');
    await expect(page.getByText('有 1 个公式未成功计算',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'确认并导出',exact:true}).click();
    await expect(page.locator('.workbook-panel .el-alert')).toContainText('请先修正公式错误并完成计算，再导出');
    await writeCell('J1','已修正');
    await expect.poll(()=>cell('0,9'),{timeout:30000}).toBe('已修正');
    await expect(page.locator('.formula-errors')).toHaveCount(0);
    console.log('CYCLE_SAVE_EXPORT_GUARD_OK');
    const definitions = [
      ['=SUM(A1:A2)',6],['=AVERAGE(A1:A2)',3],['=MIN(A1:A2)',2],['=MAX(A1:A2)',4],['=COUNT(A1:A3)',2],['=COUNTA(A1:A3)',3],
      ['=IF(A1>1,"是","否")','是'],['=IFERROR(1/0,9)',9],['=AND(TRUE,A1=2)',true],['=OR(FALSE,A1=2)',true],['=ROUND(1.235,2)',1.24],
      ['=SUMIF(A1:A2,">2",A1:A2)',4],['=COUNTIF(A1:A2,">2")',1],['=VLOOKUP("乙",B1:C2,2,FALSE)',20],['=INDEX(B1:C2,2,2)',20],['=MATCH("乙",B1:B2,0)',2],['=A1+$A$2+其他!A1',11]
    ];
    const formulaBook = await rpc('workbooks.open',{task_id:server.task_id});
    const snapshot = formulaBook.snapshot; snapshot.name='公式验收';
    const sheet = snapshot.sheets[0]; sheet.name='公式表';
    for(const [key,value] of Object.entries({'0,0':2,'1,0':4,'2,0':'项目','0,1':'甲','1,1':'乙','0,2':10,'1,2':20})) sheet.cells[key]={value,type:typeof value==='number'?'number':'string'};
    definitions.forEach(([formula],i)=>sheet.cells[`${i},4`]={formula,value:null,type:'number',result_state:'pending'});
    snapshot.sheets.push({...structuredClone(sheet),id:require('node:crypto').randomUUID().replaceAll('-',''),name:'其他',cells:{'0,0':{value:5,type:'number'}}});
    await rpc('workbooks.save',{task_id:server.task_id,snapshot,expected_version:1});
    await page.reload(); await page.getByRole('button',{name:/^库存.csv/}).first().click();
    await page.getByRole('button',{name:'公式验收 · v2',exact:true}).click();
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    await expect.poll(async()=> (await rpc('workbooks.open',{task_id:server.task_id,workbook_id:snapshot.id})).revision,{timeout:30000}).toBeGreaterThan(2);
    const calculated=await rpc('workbooks.open',{task_id:server.task_id,workbook_id:snapshot.id});
    definitions.forEach(([formula,expected],i)=>assert.equal(calculated.snapshot.sheets[0].cells[`${i},4`].value,expected,formula));
    fs.writeFileSync('build/workbook-formula-snapshot.json',JSON.stringify(calculated.snapshot));
    // A full 200,000 populated-cell editor load, distinct from paged preview.
    if(process.env.WORKBOOK_CAPACITY==='1') {
      const capacity=await rpc('workbooks.open',{task_id:server.task_id});
      capacity.snapshot.name='容量验收'; const s=capacity.snapshot.sheets[0];s.row_count=10000;
      for(let i=0;i<200000;i++)s.cells[`${Math.floor(i/20)},${i%20}`]={value:i,type:'number'};
      await rpc('workbooks.save',{task_id:server.task_id,snapshot:capacity.snapshot,expected_version:1});
      await page.reload();await page.getByRole('button',{name:/^库存.csv/}).first().click();
      const started=performance.now();await page.getByRole('button',{name:'容量验收 · v2',exact:true}).click();
      await expect(page.locator('.save-state')).toContainText('已保存',{timeout:60000});
      await page.waitForFunction(()=>[...document.querySelectorAll('.univer-container input')].some(n=>n.value==='A1'));
      const loaded=performance.now()-started;
      await writeCell('T10000','200001');
      await expect.poll(async()=> (await rpc('workbooks.open',{task_id:server.task_id,workbook_id:capacity.snapshot.id})).revision,{timeout:60000}).toBeGreaterThan(2);
      const saved=await rpc('workbooks.open',{task_id:server.task_id,workbook_id:capacity.snapshot.id});
      assert.equal(saved.snapshot.sheets[0].cells['9999,19'].value,200001);
      const savedAt=performance.now();
      await writeCell('U1','超限');
      await expect(page.getByText('操作超过 200000 个有效单元格，已拦截；可改用分页预览与全量处理',{exact:true})).toBeVisible();
      const metrics={cells:200000,load_ms:Math.round(loaded),edit_and_save_ms:Math.round(savedAt-started-loaded),heap_mb:await page.evaluate(()=>Math.round(performance.memory.usedJSHeapSize/1024**2))};
      fs.writeFileSync('build/workbook-browser-capacity.json',JSON.stringify(metrics,null,2));
    }
    await page.screenshot({path:'build/workbook-ui.png',fullPage:true,animations:'disabled'});
    fs.writeFileSync('build/workbook-ui-dom.txt',await page.locator('body').innerText());
    fs.writeFileSync('build/workbook-ui-inputs.json',JSON.stringify(await page.locator('input,textarea').evaluateAll(nodes=>nodes.map(n=>({tag:n.tagName,role:n.getAttribute('role'),aria:n.getAttribute('aria-label'),placeholder:n.getAttribute('placeholder'),value:n.value,cls:n.className}))),null,2));
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log('WORKBOOK_UI_LOADED');
  } finally {
    await page.screenshot({path:'build/workbook-ui-latest.png',fullPage:true,animations:'disabled'}).catch(()=>{});
    fs.writeFileSync('build/workbook-ui-latest-dom.txt',await page.locator('body').innerText().catch(()=>''));
    fs.writeFileSync('build/workbook-ui-errors.json',JSON.stringify({errors,external},null,2));
    await close();
  }
})().catch(e=>{console.error(e);process.exitCode=1});
