"""Real source-intake browser regression; uses explicit manual contracts, no paid calls.

Start workbench + synthetic target using README, then run this file.
Add --with-github to verify a live public repository import (network required).
All snapshots, disposable fixtures and reports stay in this workspace's ignored folders.
"""
import argparse,asyncio,hashlib,io,json,zipfile,os
from pathlib import Path
from playwright.async_api import async_playwright
from yanzhen.settings import ROOT, initialize
initialize()
OUT=ROOT/'.artifacts'; URL=os.getenv('YZ_VERIFY_UI_ORIGIN','http://127.0.0.1:8767')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--with-github',action='store_true')
args=parser.parse_args()
REQUIREMENT='填写“源码验收”并点击保存，刷新后仍显示“源码验收”。'
HTML='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>源码验收测试</title><h1>项目接入测试</h1><label>备注<textarea id="note"></textarea></label><button id="save">保存</button><p id="saved"></p><script>document.querySelector('#saved').textContent=localStorage.getItem('note')||'';document.querySelector('#save').onclick=()=>{localStorage.setItem('note',document.querySelector('#note').value);document.querySelector('#saved').textContent=localStorage.getItem('note')}</script></html>'''
contract={'id':'source-save','title':'源码静态预览保存与刷新','probes':[{'id':'saved','source_type':'dom_text','phase':'after','locator':{'by':'css','value':'#saved'}}],'constraints':{'required_actions':['fill','click','reload']},'postconditions':[{'id':'persisted','left':'saved','op':'eq','expected':'源码验收','source':{'quote':REQUIREMENT}}]}
actions=[{'id':'open','kind':'navigate','url':'.'},{'id':'fill','kind':'fill','locator':{'by':'label','value':'备注'},'value':'源码验收'},{'id':'save','kind':'click','locator':{'by':'role','role':'button','value':'保存'}},{'id':'reload','kind':'reload'}]
archive=ROOT/'.tmp/intake-ui-example.zip'
with zipfile.ZipFile(archive,'w') as z:z.writestr('index.html',HTML);z.writestr('README.md','# Static test fixture')
directory=ROOT/'.tmp/intake-directory-example';directory.mkdir(exist_ok=True);(directory/'broken.py').write_text('def broken(:',encoding='utf-8')
async def main():
 errors=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch();page=await browser.new_page(viewport={'width':1480,'height':1080});page.set_default_timeout(20000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto(URL+'/static/verifyagent.html?ui=intake-7');await page.locator('#va-service').filter(has_text='服务连接正常').wait_for()
  await page.locator('#va-own-project').click()
  config=await (await page.request.get(URL+'/api/verify/capabilities')).json()
  initial_planner=await page.locator('#va-provider').input_value()
  if config['openjiuwen']['ready'] and config['default_planner']=='openjiuwen':
   assert await page.locator('#va-provider').input_value()=='openjiuwen'
  await page.locator('[name=project-source][value=zip]').check();await page.locator('#va-zip').set_input_files(archive);await page.locator('#va-source-authorized').check();await page.locator('#va-import-project').click()
  await page.locator('#va-preview-project').wait_for()
  await page.screenshot(path=str(OUT/'intake-zip-desktop.png'),full_page=True)
  await page.locator('#va-preview-project').click();await page.wait_for_function("document.querySelector('#va-url').value.startsWith('http://127.0.0.1:')")
  await page.locator('#va-requirements').fill(REQUIREMENT);await page.locator('#va-authorized').check();await page.locator('#va-settings').evaluate('(e)=>e.open=true');await page.locator('#va-manual-settings').evaluate('(e)=>e.open=true')
  await page.locator('#va-provider').select_option('manual');await page.locator('#va-supplied').fill(json.dumps({'contracts':[contract]},ensure_ascii=False));await page.locator('#va-actions').fill(json.dumps(actions,ensure_ascii=False));await page.locator('#va-draft').click()
  await page.locator('#va-review-panel').wait_for(state='visible');await page.locator('#va-confirm').check();await page.locator('#va-freeze').click();await page.locator('#va-execution-panel').wait_for(state='visible')
  async with page.expect_response(lambda r: r.url.endswith('/api/verify/runs') and r.request.method == 'POST') as started:
   await page.locator('#va-start').click()
  run_id=(await (await started.value).json())['id']
  for _ in range(120):
   if await page.locator('#va-result-panel').is_visible():break
   if await page.locator('#va-approval').is_visible():
    await page.locator('#va-approve').click()
   await page.wait_for_timeout(500)
  assert await page.locator('#va-result-panel').is_visible(),await page.locator('#va-error').text_content()
  assert '通过' in await page.locator('#va-results').inner_text()
  import httpx
  report=httpx.get(URL+'/api/verify/runs/'+run_id,trust_env=False).json()
  assert report['results'][0]['verdict']=='pass'
  archive_bytes=httpx.get(URL+f'/api/verify/runs/{run_id}/artifacts/evidence.zip',trust_env=False).content
  with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
   assert {'project.json','source-manifest.json'}.issubset(z.namelist())
   manifest=json.loads(z.read('manifest.json'))
   for name,row in manifest['files'].items():
    assert hashlib.sha256(z.read(name)).hexdigest()==row['sha256']
  await page.screenshot(path=str(OUT/'intake-source-result.png'),full_page=True)
  await page.locator('#va-new').click();await page.locator('#va-own-project').click();await page.locator('[name=project-source][value=directory]').check();await page.locator('#va-directory').fill(str(directory));await page.locator('#va-source-authorized').check();await page.locator('#va-import-project').click();await page.locator('#va-source-report').filter(has_text='Python 静态语法检查失败').wait_for()
  for width in [1480,900,390,320]:
   await page.set_viewport_size({'width':width,'height':1000})
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
  await page.screenshot(path=str(OUT/'intake-directory-mobile.png'),full_page=True)
  await page.set_viewport_size({'width':1480,'height':1080})
  if args.with_github:
   await page.locator('[name=project-source][value=github]').check();await page.locator('#va-github').fill('https://github.com/octocat/Hello-World')
   async with page.expect_response(lambda r: r.url.endswith('/api/verify/projects') and r.request.method=='POST') as imported:
    await page.locator('#va-import-project').click()
   imported_project=await (await imported.value).json()
   assert imported_project.get('provenance',{}).get('commit'),imported_project
   await page.locator('#va-source-report').filter(has_text=imported_project['provenance']['commit'][:12]).wait_for()
  assert not errors,errors
  result={'status':'passed','zip_upload':True,'directory_snapshot_and_real_syntax_error':True,'actual_public_github_import':args.with_github,'default_planner':initial_planner,'static_preview_browser_save_reload':'PASS','source_manifest_in_evidence':True,'run_id':run_id,'widths':[1480,900,390,320],'page_errors':errors,'model_calls':0}
  (OUT/'intake-ui-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));await browser.close()
asyncio.run(main())
