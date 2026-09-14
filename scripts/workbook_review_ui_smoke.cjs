// Synthetic end-to-end candidate review, pagination, adoption, and continued editing.
const {createHarness,expect}=require('./ui_harness.cjs');
const fs=require('node:fs');const assert=require('node:assert/strict');
(async()=>{
  const { page, server, rpc, errors, close } = await createHarness();
  try {
    const task=await rpc('tasks.create',{});
    await rpc('tasks.execute',{task_id:task.id,plan:{steps:[{kind:'create_table',inputs:[],params:{name:'采购填报验收',columns:['编号','数量','备注']}}],questions:[]}});
    await expect.poll(async()=>(await rpc('tasks.get',{task_id:task.id})).task.status,{timeout:30000}).toBe('succeeded');
    await page.goto(`http://127.0.0.1:${server.port}`);
    await page.getByRole('tab',{name:/② 结果与核对/}).click();
    await expect(page.getByRole('button',{name:'采用并继续编辑',exact:true})).toBeEnabled();
    const record=(await rpc('tasks.get',{task_id:task.id})).task,output=record.outputs[0];
    const summary=await rpc('outputs.review',{task_id:task.id,output_id:output.id});
    assert.ok(summary.total>50);
    await page.locator('.el-pagination .btn-next').click();
    await expect(page.locator('.el-pagination .number.is-active')).toHaveText('2');
    await expect(page.locator('.change-table .el-table__body tr')).toHaveCount(Math.min(50,summary.total-50));
    const lastPage=Math.ceil(summary.total/50),jump=page.locator('.el-pagination__editor input');
    await jump.fill(String(lastPage));await jump.press('Enter');
    await expect(page.locator('.change-table .el-table__body tr')).toHaveCount(summary.total%50||50);
    await page.screenshot({path:'build/workbook-review.png',fullPage:true,animations:'disabled'});
    await page.getByRole('button',{name:'采用并继续编辑',exact:true}).click();
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    const adopted=await rpc('outputs.review',{task_id:task.id,output_id:output.id});assert.ok(adopted.applied_book);
    const book=await rpc('workbooks.open',{task_id:task.id,workbook_id:adopted.applied_book});
    assert.equal(book.snapshot.sheets[0].cells['0,0'].value,'编号');assert.equal(book.snapshot.sheets[0].cells['1,0'].value,null);
    let exportRequests=0;
    await page.route('**/__rpc',async route=>{
      if(route.request().postDataJSON()[0]!=='outputs.export')return route.continue();
      ++exportRequests;
      await route.fulfill({json:{ok:true,data:{exported:false}}});
    });
    await page.getByRole('tab',{name:/② 结果与核对/}).click();
    await page.getByRole('button',{name:'确认并导出',exact:true}).click();
    await expect.poll(()=>exportRequests).toBe(1);
    await expect(page.locator('.save-state')).toContainText('已保存');
    assert.equal((await rpc('outputs.review',{task_id:task.id,output_id:output.id})).exported_revision,null);
    await page.getByRole('tab',{name:/① 文件与处理/}).click();
    await page.getByRole('tab',{name:'表格编辑器',exact:true}).click();
    await expect(page.locator('.save-state')).toContainText('已保存');
    assert.equal(exportRequests,1,'A cancelled one-time export must not replay after view switching');
    await page.unroute('**/__rpc');
    const name=page.locator('.univer-container input.univer-appearance-none');await expect(name).toHaveValue('A1');
    await name.fill('A2');await name.press('Enter');await page.keyboard.insertText('00017');await page.keyboard.press('Enter');
    await expect.poll(async()=>(await rpc('workbooks.open',{task_id:task.id,workbook_id:adopted.applied_book})).revision,{timeout:30000}).toBeGreaterThan(book.revision);
    await page.screenshot({path:'build/workbook-editor.png',fullPage:true,animations:'disabled'});
    await page.reload();await page.getByRole('button',{name:/^采购填报验收 · v/}).click();
    await expect(page.locator('.save-state')).toContainText('已保存',{timeout:30000});
    await page.getByRole('tab',{name:/② 结果与核对/}).click();
    await page.getByRole('button',{name:'确认并导出',exact:true}).click();
    await expect(page.getByText(/工作簿已继续编辑，请打开当前版本重新核对并导出/)).toBeVisible();
    assert.deepEqual(errors,[]);console.log('REVIEW_PAGINATION_APPLY_REOPEN_OK');
  } finally {await page.screenshot({path:'build/workbook-review-latest.png',fullPage:true,animations:'disabled'}).catch(()=>{});await close()}
})().catch(error=>{console.error(error);process.exitCode=1});
