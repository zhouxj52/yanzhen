"""Exercise the actual dashboard workflow and capture desktop/mobile screenshots."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from yanzhen.settings import ARTIFACTS, initialize


async def main():
    initialize()
    errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1480, "height": 1100}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = await page.goto("http://127.0.0.1:8765")
        assert response.status == 200
        await page.locator(".metric-card").first.wait_for()
        records = await (await page.request.get("http://127.0.0.1:8765/api/runs")).json()
        assert await page.locator('[data-overview-metric="history"]').inner_text() == str(len(records))
        assert await page.locator("#recent-runs tr").count() == min(5, len(records))
        await page.screenshot(path=str(ARTIFACTS / "ui-overview.png"), full_page=True, animations="disabled")
        await page.locator('[data-chart-filter="fail"]').click()
        assert await page.locator('[data-chart-filter="fail"]').get_attribute("aria-pressed") == "true"
        await page.locator('[data-chart-filter="all"]').click()
        await page.locator("#toggle-sidebar").click()
        assert "sidebar-collapsed" in (await page.locator("body").get_attribute("class"))
        await page.locator("#toggle-sidebar").click()
        await page.locator('.main-nav [data-view="workbench"]').click()
        await page.get_by_test_id("analyze").click()
        assert await page.locator('#provider option[value="qwen"]').is_disabled()
        await page.locator("#bundle-status").filter(has_text="待审阅").wait_for()
        assert await page.locator(".contract-item").count() == 5
        await page.get_by_test_id("freeze").click()
        await page.locator("#bundle-status").filter(has_text="已冻结").wait_for()
        await page.get_by_test_id("run").click()
        await page.locator("#run-status").filter(has_text="验收完成").wait_for(timeout=90000)
        assert await page.locator('[data-metric="fail"]').inner_text() == "3"
        assert await page.locator('[data-metric="blocked"]').inner_text() == "0"
        await page.locator('[data-result="1"]').click()
        await page.locator("#evidence h3").filter(has_text="成员不能读取他人报销单").wait_for()
        assert await page.locator("#evidence .evidence-image").count() == 1
        await page.locator("#integrity").click()
        await page.locator("#toast").filter(has_text="证据校验通过").wait_for()
        await page.evaluate("scrollTo(0, 0)")
        await page.locator("#toast").evaluate("el => el.hidden = true")
        await page.screenshot(path=str(ARTIFACTS / "ui-desktop.png"), full_page=True, animations="disabled")
        await page.get_by_role("button", name="在新环境重放").click()
        await page.locator("#comparison").filter(has_text="判定与原运行一致").wait_for(timeout=90000)
        await page.locator('.main-nav [data-view="history"]').click()
        await page.locator(".history-item").first.wait_for()
        assert await page.locator(".history-item").count() >= 2
        run_id = await page.locator(".history-item").first.locator("button").get_attribute("data-open-run")
        await page.locator("#history-search").fill(run_id)
        assert await page.locator(".history-item").count() == 1
        await page.locator("#history-search").fill("no-such-run-id")
        await page.get_by_role("heading", name="没有匹配的运行记录").wait_for()
        await page.locator("#history-search").fill("")
        await page.locator("#history-status").select_option("cancelled")
        cancelled = page.locator(".history-item").filter(has_text="已取消")
        if await cancelled.count():
            await cancelled.first.get_by_role("button", name="查看详情").click()
            await page.locator("#run-status").filter(has_text="任务已取消").wait_for()
            assert await page.locator("#replay").is_disabled()
        await page.locator('.main-nav [data-view="evidence"]').click()
        await page.locator(".evidence-card").first.wait_for()
        assert await page.locator('.evidence-card a[href$="evidence.zip"]').count() > 0
        download_url = await page.locator('.evidence-card a[href$="evidence.zip"]').first.get_attribute("href")
        archive = await page.request.get("http://127.0.0.1:8765" + download_url)
        assert archive.status == 200 and (await archive.body()).startswith(b"PK")
        await page.locator("[data-verify-run]").first.click()
        await page.locator("#toast").filter(has_text="证据校验通过").wait_for()
        await page.keyboard.press("Control+k")
        await page.locator("#palette-search").fill(run_id)
        assert await page.locator(".palette-row").count() == 1
        await page.locator(".palette-row").click()
        await page.locator("#run-id").filter(has_text=run_id[:12]).wait_for()
        assert not await page.locator("#search-dialog").is_visible()
        await page.locator('.secondary-nav [data-view="guide"]').click()
        await page.get_by_role("heading", name="三步完成第一次验收").wait_for()
        await page.locator('.main-nav [data-view="workbench"]').click()
        await page.locator("#new-draft").click()
        assert await page.locator("#run").is_disabled()
        assert await page.locator("#contract-count").inner_text() == "0"
        await page.set_viewport_size({"width": 900, "height": 900})
        assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Tablet page has horizontal overflow"
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.locator("#toggle-sidebar").click()
        await page.locator('.main-nav [data-view="overview"]').click()
        assert "sidebar-open" not in (await page.locator("body").get_attribute("class") or "")
        await page.evaluate("scrollTo(0, 0)")
        await page.locator("#toast").evaluate("el => el.hidden = true")
        await page.screenshot(path=str(ARTIFACTS / "ui-mobile.png"), full_page=True, animations="disabled")
        overflow = await page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert not overflow, "Mobile page has horizontal overflow"
        await page.locator("#toggle-sidebar").click()
        await page.keyboard.press("Escape")
        assert not await page.locator("#sidebar-backdrop").is_visible()
        # Every view must fit narrow screens; tables scroll inside their containers.
        for width in (390, 900):
            await page.set_viewport_size({"width": width, "height": 900})
            for view in ("overview", "workbench", "history", "evidence", "guide"):
                await page.evaluate("(view) => activeView(view)", view)
                assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth"), (width, view)
        # Verify genuine first-use rendering with an empty API response.
        await page.route("**/api/runs", lambda route: route.fulfill(json=[]))
        await page.goto("http://127.0.0.1:8765/#overview")
        await page.reload()
        await page.get_by_role("heading", name="还没有运行记录").wait_for()
        assert await page.locator('[data-overview-metric="history"]').inner_text() == "0"
        await page.evaluate("activeView('evidence')")
        await page.get_by_role("heading", name="还没有归档证据").wait_for()
        assert not errors, errors
        await browser.close()
    result = {"desktop": "passed", "mobile": "passed", "replay": "passed", "overview_data": "passed", "search_and_filters": "passed", "archive_download_and_integrity": "passed", "empty_state": "passed", "page_errors": errors, "screenshots": [str(ARTIFACTS / name) for name in ("ui-overview.png", "ui-desktop.png", "ui-mobile.png")]}
    (ARTIFACTS / "ui-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
