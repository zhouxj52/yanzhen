"""Real-browser verification of independent upstream app and reduced reproduction."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from yanzhen.exports import verify_evidence
from yanzhen.settings import ARTIFACTS, initialize

ORIGIN="http://127.0.0.1:8765"


async def main():
    initialize()
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={"width":1480,"height":1100})
        page.on("pageerror",lambda e:errors.append(str(e)))
        await page.goto(ORIGIN)
        await page.locator(".metric-card").first.wait_for()
        await page.locator('.main-nav [data-view="workbench"]').click()
        await page.locator("#target").select_option("todomvc")
        await page.locator("#analyze").click()
        await page.locator("#bundle-status").filter(has_text="待审阅").wait_for()
        assert await page.locator(".contract-item").count()==3
        await page.locator("#freeze").click()
        await page.locator("#bundle-status").filter(has_text="已冻结").wait_for()
        await page.locator("#run").click()
        await page.locator("#run-status").filter(has_text="验收完成").wait_for(timeout=120000)
        assert await page.locator('[data-metric="pass"]').inner_text()=="2"
        assert await page.locator('[data-metric="fail"]').inner_text()=="1"
        assert await page.locator('[data-metric="blocked"]').inner_text()=="0"
        assert await page.locator(".conflict-callout").count()==1
        assert await page.locator(".verify-recipe").count()==1
        run_id=await page.evaluate("state.run.id")
        digest=await page.evaluate("state.run.digest")
        report=await page.evaluate("state.run")
        reduction=report["reproductions"][0]
        assert reduction["steps"]==["新增任务","刷新页面"]
        assert reduction["status"]=="verified" and reduction["confirmations"]==2
        assert verify_evidence(ARTIFACTS/"runs"/run_id/"evidence.zip")["valid"]
        await page.locator(".verify-recipe").click()
        await page.locator("#toast").filter(has_text="精简步骤已在新环境复现").wait_for(timeout=60000)
        for case in ("assertion","role","skip"):
            await page.locator("#repair-case").select_option(case)
            await page.locator("#review-repair").click()
            await page.locator("#repair-verdict").filter(has_text="已拦截").wait_for()
        await page.locator("#repair-case").select_option("locator")
        await page.locator("#review-repair").click()
        await page.locator("#repair-verdict").filter(has_text="审查通过").wait_for()
        await page.evaluate("scrollTo(0,0)")
        await page.locator("#toast").evaluate("el=>el.hidden=true")
        await page.screenshot(path=str(ARTIFACTS/"innovation-desktop.png"),full_page=True,animations="disabled")
        await page.locator("#reproductions").screenshot(path=str(ARTIFACTS/"innovation-reduction.png"),animations="disabled")
        # Run the exact reduced-script artifact, not the whole-contract replay.
        script=ARTIFACTS/"runs"/run_id/"reproduce.py"
        executed=await asyncio.to_thread(subprocess.run,[sys.executable,str(script)],capture_output=True,text=True,encoding="utf-8",timeout=70)
        assert executed.returncode==0,executed.stderr
        script_report=json.loads(executed.stdout)
        assert script_report["matches"] and script_report["steps"]==["新增任务","刷新页面"]
        # Same frozen requirements against a separately labelled local repair.
        await page.locator("#scenario").select_option("healthy")
        await page.locator("#run").click()
        await page.locator("#run-status").filter(has_text="验收完成").wait_for(timeout=90000)
        assert await page.locator('[data-metric="pass"]').inner_text()=="3"
        assert await page.locator('[data-metric="fail"]').inner_text()=="0"
        assert await page.evaluate("state.run.digest")==digest
        assert not await page.locator(".conflict-callout").count()
        fixed_run=await page.evaluate("state.run.id")
        for width in (900,390):
            await page.set_viewport_size({"width":width,"height":900})
            assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth"),width
        # Load original failing report again for narrow-screen evidence/reduction QA.
        await page.evaluate("(id)=>openRun(id)",run_id)
        await page.locator(".verify-recipe").wait_for()
        assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth")
        await page.evaluate("scrollTo(0,0)")
        await page.screenshot(path=str(ARTIFACTS/"innovation-mobile.png"),full_page=True,animations="disabled")
        assert not errors,errors
        await browser.close()
    output={"upstream_run":run_id,"fixed_run":fixed_run,"digest":digest,"upstream":{"pass":2,"fail":1},"local_repair":{"pass":3,"fail":0},"reduced_steps":reduction["steps"],"trials":len(reduction["trials"]),"independent_confirmations":reduction["confirmations"],"downloaded_script":"passed","repair_guard":"passed","evidence_integrity":"passed","responsive":"passed","page_errors":errors}
    (ARTIFACTS/"innovation-check.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(output,ensure_ascii=False))


if __name__=="__main__":
    asyncio.run(main())
