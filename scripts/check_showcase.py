"""Validate and record the actual presentation, including proof images and failure states."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright
from yanzhen.settings import ARTIFACTS, initialize

ORIGIN="http://127.0.0.1:8765"


async def main():
    initialize()
    output=ARTIFACTS/"demo"
    output.mkdir(exist_ok=True)
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={"width":1440,"height":1000},device_scale_factor=1,record_video_dir=str(output),record_video_size={"width":1440,"height":1000})
        page=await context.new_page()
        page.on("pageerror",lambda e:errors.append(str(e)))
        await page.goto(ORIGIN+"/#showcase")
        await page.locator("#demo-start").wait_for()
        await page.locator("#service-status").filter(has_text="服务连接正常").wait_for()
        await page.locator("#demo-fullscreen").click()
        await page.screenshot(path=str(output/"01-intro.png"),animations="disabled")
        await page.wait_for_timeout(1600)
        await page.locator("#demo-start").click()
        await page.wait_for_function("showcase.chapter===2 && !!showcase.original",timeout=120000)
        await page.locator(".proof-image img").first.wait_for()
        await page.wait_for_function("Array.from(document.querySelectorAll('.proof-image img')).every(img=>img.complete && img.naturalWidth>0)")
        assert await page.locator(".proof-image img").count()==2
        await page.screenshot(path=str(output/"03-evidence.png"),animations="disabled")
        await page.wait_for_function("showcase.chapter===3",timeout=30000)
        await page.screenshot(path=str(output/"04-reduction.png"),animations="disabled")
        await page.locator("#demo-session-state").filter(has_text="本次演示已完成").wait_for(timeout=120000)
        assert not await page.locator(".demo-error").count()
        report=await page.evaluate("({original:showcase.original,fixed:showcase.fixed,bundle:showcase.bundle})")
        assert report["original"]["summary"]=={"pass":2,"fail":1,"blocked":0,"unclear":0}
        assert report["fixed"]["summary"]=={"pass":3,"fail":0,"blocked":0,"unclear":0}
        assert report["original"]["digest"]==report["fixed"]["digest"]
        reproduction=report["original"]["reproductions"][0]
        assert reproduction["steps"]==["新增任务","刷新页面"] and reproduction["confirmations"]==2
        await page.locator("#demo-guard").click()
        await page.locator("#demo-guard-result").filter(has_text="已拦截").wait_for()
        await page.screenshot(path=str(output/"05-closure.png"),animations="disabled")
        await page.wait_for_timeout(4000)
        # Review all chapters after completion and exercise manual navigation.
        await page.locator('[data-chapter="2"]').click()
        assert await page.locator(".proof-image img").count()==2
        await page.locator("#demo-next").click()
        await page.locator(".trial-preview summary").click()
        assert await page.locator(".trial-preview p").count()==len(reproduction["trials"])
        await page.wait_for_timeout(3500)
        await page.locator('[data-chapter="4"]').click()
        await page.wait_for_timeout(1500)
        # The recording ends here. Responsive/error checks use a separate page.
        video=page.video
        await context.close()
        await video.save_as(str(output/"yanzhen-demo.webm"))
        original_video=Path(await video.path())
        if original_video != output/"yanzhen-demo.webm" and original_video.parent.resolve()==output.resolve():
            original_video.unlink()
        qa=await browser.new_page(viewport={"width":390,"height":844})
        qa.on("pageerror",lambda e:errors.append(str(e)))
        await qa.goto(ORIGIN+"/#showcase")
        await qa.locator("#service-status").filter(has_text="服务连接正常").wait_for()
        # Reuse the already executed real records to inspect each mobile chapter.
        await qa.evaluate("(reports)=>{showcase.bundle=reports.bundle;showcase.original=reports.original;showcase.fixed=reports.fixed;showcase.reached=4;renderDemoScene();}",report)
        for width in (390,900,1440):
            await qa.set_viewport_size({"width":width,"height":900})
            for chapter in range(5):
                await qa.evaluate("(n)=>{showcase.chapter=n;renderDemoScene();}",chapter)
                assert not await qa.evaluate("document.documentElement.scrollWidth>innerWidth"),(width,chapter)
            for view in ("overview","workbench","history","evidence","guide","showcase"):
                await qa.evaluate("(name)=>activeView(name)",view)
                assert not await qa.evaluate("document.documentElement.scrollWidth>innerWidth"),(width,view)
        await qa.set_viewport_size({"width":390,"height":844})
        await qa.evaluate("showcase.chapter=2;renderDemoScene();scrollTo(0,0)")
        await qa.screenshot(path=str(output/"mobile-evidence.png"),full_page=True,animations="disabled")
        # Opening full reports must exit focused presentation mode.
        await qa.set_viewport_size({"width":1440,"height":1000})
        await qa.evaluate("showcase.chapter=4;renderDemoScene()")
        await qa.locator("#demo-fullscreen").click()
        await qa.locator("#demo-open-original").click()
        await qa.locator("#run-id").filter(has_text=report["original"]["id"][:12]).wait_for()
        assert "focus-demo" not in (await qa.locator("body").get_attribute("class") or "")
        # Unavailable backend must be an error state, not a successful presentation.
        await qa.evaluate("activeView('showcase')")
        await qa.route("**/api/analyze",lambda route:route.fulfill(status=503,json={"detail":"测试：验收服务暂不可用"}))
        await qa.locator("#demo-start").click()
        await qa.locator(".demo-error").filter(has_text="服务暂不可用").wait_for()
        assert await qa.locator("#demo-session-state").inner_text()=="执行遇到问题"
        await qa.unroute("**/api/analyze")
        # Stop during narration before a browser run is created.
        await qa.locator("#demo-start").click()
        await qa.wait_for_function("showcase.busy && showcase.bundle!==null")
        await qa.locator("#demo-start").click()
        await qa.locator("#demo-session-state").filter(has_text="已停止").wait_for()
        assert not await qa.evaluate("showcase.busy")
        await qa.evaluate("configureTarget('todomvc',true);activeView('overview')")
        await qa.locator('[data-project-target="reimbursement"]').click()
        assert await qa.locator("#target").input_value()=="reimbursement"
        await qa.evaluate("activeView('overview');scrollTo(0,0)")
        await qa.screenshot(path=str(output/"new-workspace.png"),full_page=True,animations="disabled")
        assert not errors,errors
        await browser.close()
    result={"status":"passed","original_run":report["original"]["id"],"fixed_run":report["fixed"]["id"],"same_contract":True,"real_before_after_images":True,"reduction":reproduction["steps"],"independent_confirmations":2,"guard":"passed","responsive":"390/900/1440 passed","unavailable_backend":"error reported","stop":"passed","page_errors":errors,"video":str(output/"yanzhen-demo.webm")}
    (output/"demo-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    asyncio.run(main())
