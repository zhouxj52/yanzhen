"""Run an actual persistence check plus an intentionally unimplemented requirement.

Only the owned localhost fixture is written to; provider calls are forbidden.
All new reports/screenshots stay in the D-drive workspace artifact directory.
"""
import asyncio
import hashlib
import io
import json
import os
import zipfile

from playwright.async_api import async_playwright
from yanzhen.settings import ROOT, initialize

URL=os.getenv('YZ_VERIFY_UI_ORIGIN','http://127.0.0.1:8767')


async def main():
    initialize()
    errors=[];forbidden=[]
    from yanzhen import store
    ledger=store.ARTIFACTS/'verifyagent/model-budget.json'
    before=hashlib.sha256(ledger.read_bytes()).hexdigest() if ledger.is_file() else None
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':1480,'height':1080})
        page.set_default_timeout(20000)
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def gate(route):
            request=route.request
            if request.method=='POST' and request.url.endswith(('/analyze','/runs')):
                body=request.post_data_json
                if body.get('provider',body.get('planner'))!='manual':
                    forbidden.append(request.url);await route.abort();return
            await route.continue_()
        await page.route('**/*',gate)
        try:
            await page.goto(URL+'/static/verifyagent.html?ui=coverage-9')
            await page.locator('#va-service').filter(has_text='服务连接正常').wait_for()
            await page.locator('#va-try-demo').click()
            await page.locator('[data-example="persistence"]').click()
            await page.locator('#va-example-note').wait_for(state='visible')
            original=await page.locator('#va-requirements').input_value()
            await page.locator('#va-requirements').fill(original+'\n验收报告应支持导出 PDF。')
            await page.locator('#va-authorized').check()
            await page.locator('#va-draft').click()
            await page.locator('#va-review-panel').wait_for(state='visible')
            await page.locator('#va-coverage-preview').locator('..').locator('> summary').click()
            await page.locator('#va-coverage-preview [data-coverage-state=uncovered]').wait_for()
            assert 'PDF' in await page.locator('#va-coverage-preview [data-coverage-state=uncovered]').inner_text()
            await page.locator('#va-confirm').check();await page.locator('#va-freeze').click()
            async with page.expect_response(lambda r:r.url.endswith('/api/verify/runs') and r.request.method=='POST') as started:
                await page.locator('#va-start').click()
            run_id=(await (await started.value).json())['id']
            for _ in range(160):
                if await page.locator('#va-result-panel').is_visible():break
                if await page.locator('#va-approval').is_visible():await page.locator('#va-approve').click()
                await page.wait_for_timeout(300)
            else:raise AssertionError('Actual fixture run did not finish')
            coverage=page.locator('#va-coverage')
            await coverage.locator('[data-coverage-state=failed]').first.wait_for()
            assert await coverage.locator('[data-coverage-state=uncovered]').count()==1
            await coverage.locator('[data-coverage-filter=gaps]').click()
            assert await coverage.locator('[data-coverage-state]:visible').count()==1
            assert 'PDF' in await coverage.locator('[data-coverage-state]:visible').inner_text()
            await coverage.locator('[data-coverage-filter=problems]').click()
            assert await coverage.locator('[data-coverage-state=uncovered]:visible').count()==0
            await coverage.locator('[data-coverage-filter=all]').click()
            check=coverage.locator('.va-coverage-check').filter(has=page.locator('.va-verdict.fail')).first
            await check.locator('> summary').click()
            await check.locator('.va-coverage-proof > summary').first.click()
            assert '实际值' in await check.inner_text()
            assert await check.locator('a').count()>0
            response=await page.request.get(URL+'/api/verify/runs/'+run_id)
            report=await response.json()
            assert report['coverage']['summary']['uncovered']==1 and report['coverage']['summary']['failed']>=1
            archive=await page.request.get(URL+'/api/verify/runs/'+run_id+'/artifacts/evidence.zip')
            with zipfile.ZipFile(io.BytesIO(await archive.body())) as z:
                manifest=json.loads(z.read('manifest.json'))
                assert 'requirement-coverage.json' in manifest['files']
                for name,item in manifest['files'].items():
                    assert hashlib.sha256(z.read(name)).hexdigest()==item['sha256']
                assert json.loads(z.read('requirement-coverage.json'))['summary']==report['coverage']['summary']
            for width in (1480,900,390,320):
                await page.set_viewport_size({'width':width,'height':1080})
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
            await page.set_viewport_size({'width':1480,'height':1080})
            await coverage.scroll_into_view_if_needed()
            await page.screenshot(path=str(ROOT/'.artifacts/requirement-coverage-desktop.png'),animations='disabled')
            await page.reload()
            await page.locator('#va-coverage [data-coverage-state=uncovered]').wait_for()
            await page.set_viewport_size({'width':390,'height':1000})
            await page.locator('#va-coverage').scroll_into_view_if_needed()
            await page.screenshot(path=str(ROOT/'.artifacts/requirement-coverage-mobile.png'),animations='disabled')
            assert not errors,errors
            assert not forbidden,forbidden
            after=hashlib.sha256(ledger.read_bytes()).hexdigest() if ledger.is_file() else None
            assert before==after
            output={'status':'passed','run_id':run_id,'coverage':report['coverage']['summary'],
                    'uncovered_original_requirement_visible':True,'direct_observation_and_real_step_links':True,
                    'filters':True,'refresh_restores':True,'archive_hashes':True,'responsive':[1480,900,390,320],
                    'page_errors':errors,'model_requests':0,'paid_ledger_unchanged':True,
                    'view_url':URL+'/static/verifyagent.html?ui=coverage-9&run='+run_id}
            (ROOT/'.artifacts/requirement-coverage-ui.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(output,ensure_ascii=False))
        except Exception:
            await page.screenshot(path=str(ROOT/'.artifacts/requirement-coverage-error.png'),full_page=True)
            raise
        finally:await browser.close()


if __name__=='__main__':asyncio.run(main())
