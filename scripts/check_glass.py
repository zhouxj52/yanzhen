"""Browser QA for glass materials and model selection. No real model calls."""
import asyncio
import json
import os

from playwright.async_api import async_playwright
from yanzhen.settings import ARTIFACTS, initialize

ORIGIN=os.getenv("YZ_ORIGIN","http://127.0.0.1:8765")


async def main():
    initialize()
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={"width":1480,"height":1080})
        page.on("pageerror",lambda e:errors.append(str(e)))
        await page.goto(ORIGIN)
        await page.locator("#service-status").filter(has_text="服务连接正常").wait_for()
        assert await page.locator('#provider option[value="deepseek"]').is_disabled()
        assert await page.locator('#demo-provider option[value="deepseek"]').is_disabled()
        material=await page.locator(".sidebar").evaluate("el=>({filter:getComputedStyle(el,'::before').backdropFilter,background:getComputedStyle(el,'::before').backgroundColor,position:getComputedStyle(el).position})")
        assert "blur" in material["filter"] and "url(" in material["filter"]
        assert material["background"].startswith("rgba(") and material["position"]=="fixed"
        assert await page.locator('.card').first.evaluate("el=>getComputedStyle(el).backdropFilter")=="none"
        await page.evaluate("document.fonts.ready")
        # Compare the same live backdrop with / without displacement. No image overlay.
        baseline=await page.locator('.sidebar').screenshot(animations="disabled")
        assert baseline==await page.locator('.sidebar').screenshot(animations="disabled")
        await page.locator('#yz-liquid-0 feDisplacementMap').evaluate("el=>el.setAttribute('scale','0')")
        flat=await page.locator('.sidebar').screenshot(animations="disabled")
        assert baseline!=flat,"The SVG lens must change the rendered backdrop"
        await page.locator('#yz-liquid-0 feDisplacementMap').evaluate("el=>el.setAttribute('scale','18')")
        await page.screenshot(path=str(ARTIFACTS/"glass-overview.png"),full_page=True,animations="disabled")
        await page.locator('.main-nav [data-view="showcase"]').click()
        await page.screenshot(path=str(ARTIFACTS/"liquid-theater.png"),full_page=True,animations="disabled")
        await page.locator("#demo-start").click()
        await page.locator("#demo-session-state").filter(has_text="本次演示已完成").wait_for(timeout=150000)
        assert await page.evaluate("showcase.original.summary.fail")==1
        assert await page.evaluate("showcase.fixed.summary.fail")==0
        assert await page.evaluate("showcase.bundle.provider")=="offline"
        await page.locator('[data-chapter="2"]').click()
        await page.wait_for_function("Array.from(document.querySelectorAll('.proof-image img')).every(el=>el.complete&&el.naturalWidth>0)")
        await page.evaluate("scrollTo(0,0)")
        await page.screenshot(path=str(ARTIFACTS/"glass-demo.png"),full_page=True,animations="disabled")
        for width in (390,900,1480):
            await page.set_viewport_size({"width":width,"height":900})
            for view in ("overview","showcase","workbench","history","evidence","guide"):
                await page.evaluate("(view)=>activeView(view)",view)
                assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth"),(width,view)
            await page.evaluate("activeView('showcase')")
            for chapter in range(5):
                await page.evaluate("n=>{showcase.chapter=n;renderDemoScene()}",chapter)
                assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth"),(width,chapter)
        await page.evaluate("showcase.chapter=4;renderDemoScene();scrollTo(0,0)")
        await page.locator('#demo-guard').click()
        await page.locator('#demo-guard-result').filter(has_text='已拦截').wait_for()
        await page.screenshot(path=str(ARTIFACTS/"liquid-closure.png"),full_page=True,animations="disabled")
        await page.set_viewport_size({"width":390,"height":844})
        await page.evaluate("activeView('showcase');showcase.chapter=2;renderDemoScene();scrollTo(0,0)")
        await page.screenshot(path=str(ARTIFACTS/"glass-mobile.png"),full_page=True,animations="disabled")
        # UI-only protocol check: advertise model availability, intercept analysis,
        # and verify explicit DeepSeek selection never falls back after an error.
        config=await (await page.request.get(ORIGIN+"/api/config")).json()
        config["model_enabled"]=True
        config["providers"]["deepseek"].update(enabled=True,configured=True)
        await page.route("**/api/config",lambda route:route.fulfill(json=config))
        selected=[]
        async def reject_analysis(route):
            selected.append(route.request.post_data_json["provider"])
            await route.fulfill(status=503,json={"detail":"测试：模型接口暂不可用"})
        await page.route("**/api/analyze",reject_analysis)
        await page.goto(ORIGIN+"/#showcase")
        await page.reload()
        await page.locator("#service-status").filter(has_text="服务连接正常").wait_for()
        await page.locator("#demo-provider").select_option("deepseek")
        await page.locator("#demo-start").click()
        await page.locator(".demo-error").filter(has_text="模型接口暂不可用").wait_for()
        assert selected==["deepseek"]
        assert await page.evaluate("showcase.bundle===null")
        await page.evaluate("activeView('workbench')")
        await page.locator("#provider").select_option("deepseek")
        await page.locator("#provider-help").filter(has_text="DeepSeek").wait_for()
        await page.locator("#analyze").click()
        await page.locator("#toast").filter(has_text="模型接口暂不可用").wait_for()
        assert selected==["deepseek","deepseek"]
        assert await page.locator("#contract-count").inner_text()=="0"
        assert not errors,errors
        await browser.close()
    result={"status":"passed","material":material,"real_backdrop_displacement":"rendered pixels differ at scale 18 vs 0","content_layer":"opaque; no blur","desktop_and_mobile":"390/900/1480; six views and five demo chapters passed","offline_demo":"passed","guard":"passed","deepseek_selection":"mocked API request verified","model_error_fallback":"none","real_model_calls":0,"page_errors":errors}
    (ARTIFACTS/"glass-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    asyncio.run(main())
