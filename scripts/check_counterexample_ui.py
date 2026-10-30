"""Real browser regression for blind source mutation, human confirmation and evidence export.

Start workbench and fixture using README. This script calls no model provider;
it authorizes only synthetic local fixture writes and the frozen trace replays.
Run: .venv/Scripts/python.exe scripts/check_counterexample_ui.py
"""
import asyncio,json,hashlib,io,zipfile,os
from pathlib import Path
from playwright.async_api import async_playwright
from yanzhen.settings import initialize,ROOT
initialize()
URL=os.getenv('YZ_VERIFY_UI_ORIGIN','http://127.0.0.1:8767')
async def main():
 errors=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch();page=await browser.new_page(viewport={'width':1480,'height':1080});page.set_default_timeout(20000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto(URL+'/static/verifyagent.html?ui=challenge-8');await page.locator('#va-service').filter(has_text='服务连接正常').wait_for()
  await page.locator('#va-try-demo').click();await page.locator('#va-challenge-example').click();await page.locator('#va-setup-panel').wait_for(state='visible')
  await page.locator('#va-authorized').check();await page.locator('#va-draft').click();await page.locator('#va-review-panel').wait_for(state='visible')
  await page.locator('#va-confirm').check();await page.locator('#va-freeze').click();await page.locator('#va-execution-panel').wait_for(state='visible')
  async with page.expect_response(lambda r:r.url.endswith('/api/verify/runs') and r.request.method=='POST') as start:
   await page.locator('#va-start').click()
  baseline=(await (await start.value).json())['id']
  for _ in range(100):
   if await page.locator('#va-result-panel').is_visible():break
   if await page.locator('#va-approval').is_visible():await page.locator('#va-approve').click()
   await page.wait_for_timeout(500)
  assert '通过' in await page.locator('#va-results').inner_text()
  await page.locator('#va-challenge-tools').evaluate('(e)=>e.open=true');await page.locator('#va-discover-challenges').click();await page.locator('[data-mutation]').first.wait_for()
  await page.locator('#va-prepare-challenge').click();await page.locator('#va-challenge-plan').wait_for(state='visible')
  assert '分配承诺' in await page.locator('#va-challenge-plan').inner_text()
  await page.locator('#va-challenge-consent').check()
  async with page.expect_response(lambda r:'/challenges/' in r.url and r.url.endswith('/start')) as response:
   await page.locator('#va-start-challenge').click()
  campaign=(await (await response.value).json())['id']
  await page.locator('#va-challenge-results').filter(has_text='揭晓结果').wait_for(timeout=120000)
  report=await (await page.request.get(URL+'/api/verify/challenges/'+campaign)).json()
  assert report['state']=='completed' and report['metrics']['trace']['detected']==1 and report['metrics']['trace']['survived']==1,report
  payload=await (await page.request.get(URL+'/api/verify/challenges/'+campaign+'/export')).body()
  with zipfile.ZipFile(io.BytesIO(payload)) as archive:
   manifest=json.loads(archive.read('manifest.json'))
   for name,row in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==row['sha256']
  await page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
  await page.screenshot(path=str(ROOT/'.artifacts/challenge-ui-desktop.png'),full_page=True,animations='disabled')
  for width in [1480,900,390,320]:
   await page.set_viewport_size({'width':width,'height':1000});assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
  await page.screenshot(path=str(ROOT/'.artifacts/challenge-ui-mobile.png'),full_page=True,animations='disabled')
  await page.reload();await page.locator('#va-challenge-results').filter(has_text='揭晓结果').wait_for()
  assert not errors,errors
  result={'status':'passed','baseline_run':baseline,'campaign':campaign,'real_browser_mutation_detected':1,'surviving_mutation':1,'committed_assignment_reveal':True,'zip_hashes':True,'reload_restores_campaign':True,'widths':[1480,900,390,320],'page_errors':errors,'model_calls':0}
  (ROOT/'.artifacts/challenge-ui-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
  await browser.close()
asyncio.run(main())
