const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright/test');
const {pathToFileURL}=require('node:url');
const path=require('node:path');const fs=require('node:fs');
(async()=>{
 const {createServer}=await import(pathToFileURL(path.resolve('gui/node_modules/vite/dist/node/index.js')).href);
 const server=await createServer({root:path.resolve('gui'),server:{host:'127.0.0.1',port:0},configFile:false});await server.listen();
 const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/engine.html`);await page.waitForFunction(()=>window.engineResult,undefined,{timeout:90000});const result=await page.evaluate(()=>window.engineResult);fs.writeFileSync('build/workbook-engine-result.json',JSON.stringify(result,null,2));if(!result.passed)throw new Error(JSON.stringify(result));console.log('ENGINE_CHECKS_OK',result.checks.join(', '))}finally{await browser.close();await server.close()}
})().catch(error=>{console.error(error);process.exitCode=1})
