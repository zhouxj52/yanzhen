"""Walk the novice entry, read-only connection check and real local demo in Chromium.

This harness explicitly approves only synthetic local fixture operations.
All analyze requests are asserted to be manual; no paid model call is made.
"""
import asyncio
import hashlib
import io
import json
import os
import zipfile

from playwright.async_api import async_playwright
from yanzhen.settings import ROOT, initialize

ORIGIN=os.getenv('YZ_VERIFY_UI_ORIGIN','http://127.0.0.1:8767')
OUTPUT=ROOT/'.artifacts'


async def main():
    initialize();errors=[];model_requests=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':1480,'height':1080})
        page.set_default_timeout(20000)
        page.on('pageerror',lambda e:errors.append(str(e)))
        def inspect_request(request):
            if request.url.endswith('/api/verify/analyze'):
                body=request.post_data_json
                if body.get('provider')!='manual':model_requests.append(body.get('provider'))
        page.on('request',inspect_request)
        try:
            await page.goto(ORIGIN+'/static/verifyagent.html')
            await page.locator('#va-service').filter(has_text='服务连接正常').wait_for()
            assert await page.locator('#va-welcome').is_visible()
            assert not await page.locator('#va-workspace').is_visible()
            assert not await page.locator('#va-contract-editor').is_visible()
            assert not await page.locator('#va-result-panel').is_visible()
            assert '不能上传源码并自动启动' in await page.locator('#va-welcome').inner_text()
            await page.screenshot(path=str(OUTPUT/'verifyagent-start-desktop.png'),full_page=True,animations='disabled')
            await page.set_viewport_size({'width':390,'height':900})
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            await page.screenshot(path=str(OUTPUT/'verifyagent-start-mobile.png'),full_page=True,animations='disabled')
            await page.set_viewport_size({'width':1480,'height':1080})
            # A new user can understand the required inputs, and receives a
            # real server-side explanation for a target outside the allowlist.
            await page.locator('#va-own-project').click()
            await page.locator('#va-url').fill('http://127.0.0.1:59999/')
            await page.locator('#va-requirements').fill('可用库存不能为负数。')
            await page.locator('#va-authorized').check()
            await page.locator('#va-check-target').click()
            await page.locator('#va-connection[data-state=error]').wait_for()
            assert '尚未获得服务器授权' in await page.locator('#va-connection').inner_text()
            # Authorized, real API entry: connection verification alone does
            # not generate a contract or incur any model use.
            await page.locator('#va-url').fill('http://127.0.0.1:8771/inventory/healthy/stock')
            await page.locator('#va-interface').select_option('api')
            await page.locator('#va-check-target').click()
            await page.locator('#va-connection[data-state=ready]').wait_for()
            assert not await page.locator('#va-review-panel').is_visible()
            await page.locator('#va-new').click()
            assert await page.locator('#va-welcome').is_visible()
            assert await page.locator('#va-url').input_value()==''
            # Entire example path works without opening a developer/JSON editor.
            await page.locator('#va-try-demo').click()
            await page.locator('[data-example="persistence"]').click()
            await page.locator('#va-example-note').wait_for(state='visible')
            assert not await page.locator('#va-supplied').is_visible()
            assert '不会调用大模型' in await page.locator('#va-example-note').inner_text()
            await page.locator('#va-authorized').check()
            await page.locator('#va-draft').click()
            await page.locator('#va-contract-state').filter(has_text='版本 1').wait_for()
            assert await page.locator('#va-contract-summary').is_visible()
            assert '怎样才算满足要求' in await page.locator('#va-contract-summary').inner_text()
            assert not await page.locator('#va-contract-editor').is_visible()
            assert await page.locator('#va-freeze').is_disabled()
            assert not await page.locator('#va-execution-panel').is_visible()
            await page.locator('#va-confirm').check();await page.locator('#va-freeze').click()
            await page.locator('#va-start').wait_for(state='visible')
            assert not await page.locator('#va-result-panel').is_visible()
            # Advanced revision remains available and never overwrites the
            # previously confirmed version. Ordinary users can skip this.
            await page.locator('#va-show-review').click()
            history_before=await page.locator('#va-digest').inner_text()
            await page.locator('#va-contract-advanced > summary').click()
            content=json.loads(await page.locator('#va-contract-editor').input_value())
            content['contracts'][0]['title']='已审阅的保存与刷新一致性'
            await page.locator('#va-contract-editor').fill(json.dumps(content,ensure_ascii=False,indent=2))
            await page.locator('#va-revise').click()
            await page.locator('#va-contract-state').filter(has_text='版本 2').wait_for()
            assert await page.locator('#va-digest').inner_text()!=history_before
            await page.locator('#va-confirm').check();await page.locator('#va-freeze').click()
            await page.locator('#va-start').click()

            async def finish(expected):
                approvals=0
                for _ in range(500):
                    if await page.locator('#va-approval').is_visible():
                        assert await page.locator('#va-approval-description').inner_text()
                        assert not await page.locator('#va-approval-action').is_visible()
                        await page.locator('#va-approve').click();approvals+=1
                    status=await page.locator('#va-run-state').get_attribute('data-status')
                    if status=='completed':break
                    assert status!='error',await page.locator('#va-run-state').inner_text()
                    await page.wait_for_timeout(200)
                else:raise AssertionError('UI run did not complete')
                assert approvals>=2
                assert await page.locator('.va-verdict.'+expected).count()>=1
                assert await page.locator('#va-result-panel').is_visible()

            await finish('fail')
            assert await page.locator('#va-graph .contradicts').count()>0
            assert '发现问题 1 项' in await page.locator('#va-result-summary').inner_text()
            assert not await page.locator('#va-error').is_visible(),await page.locator('#va-error').inner_text()
            await page.evaluate('scrollTo(0,0)')
            await page.screenshot(path=str(OUTPUT/'verifyagent-ui-failure.png'),full_page=True,animations='disabled')
            link=await page.locator('#va-export').get_attribute('href')
            data=await (await page.request.get(ORIGIN+link)).body()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                manifest=json.loads(archive.read('manifest.json'))
                for name,row in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==row['sha256']
            await page.locator('#va-repair-tools > summary').click()
            await page.locator('#va-replay-consent').check()
            await page.locator('[data-minimize]').first.click()
            await page.wait_for_function("document.querySelector('#va-reproductions').textContent.includes('verified')",timeout=180000)
            await page.locator('#va-repair-target').fill('http://127.0.0.1:8771/app/healthy/')
            await page.locator('#va-repair').click()
            await page.wait_for_function("document.querySelector('#va-run-state').dataset.status!=='completed'")
            await finish('pass')
            assert '修复版本已按原清单全部通过' in await page.locator('#va-reproductions').inner_text()
            assert '/app/healthy/' in await page.locator('#va-ready-summary').inner_text()
            for width in (1480,900,390):
                await page.set_viewport_size({'width':width,'height':1000})
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
            await page.screenshot(path=str(OUTPUT/'verifyagent-ui-mobile.png'),full_page=True,animations='disabled')
            await page.set_viewport_size({'width':1480,'height':1080})
            await page.evaluate('scrollTo(0,0)')
            await page.screenshot(path=str(OUTPUT/'verifyagent-ui-repair.png'),full_page=True,animations='disabled')
            assert not errors,errors
            assert not model_requests,model_requests
        except Exception:
            await page.screenshot(path=str(OUTPUT/'verifyagent-onboarding-error.png'),full_page=True,animations='disabled')
            raise
        finally:await browser.close()
    result={'status':'passed','first_visit_guidance':True,'source_upload_limit_explicit':True,'real_connection_check':True,'allowlist_error_actionable':True,'ordinary_flow_without_json':True,'real_http_and_browser_execution':True,'manual_mode_explicit':True,'contract_revision':True,'per_action_approval':True,'cross_layer_evidence':True,'trusted_trace_minimization':True,'same_oracle_repair_validation':True,'archive_hashes':True,'responsive':'1480/900/390','model_calls':len(model_requests),'page_errors':errors}
    (OUTPUT/'verifyagent-ui-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


asyncio.run(main())
