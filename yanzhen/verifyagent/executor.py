"""Trusted Web/API tools. No eval, shell, caller scripts, or caller-authored evidence."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx

from .schema import Action, Evidence, Locator, Probe, Run, Target, now, digest
from .security import PolicyError, Redactor, TargetPolicy, secret_headers
from .repository import path


def json_pointer(value, pointer: str):
    for part in pointer.split("/")[1:] if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def locate(page, locator: Locator):
    if locator.by == "role":
        return page.get_by_role(locator.role, name=locator.value, exact=True)
    if locator.by == "label":
        return page.get_by_label(locator.value, exact=True)
    if locator.by == "placeholder":
        return page.get_by_placeholder(locator.value, exact=True)
    if locator.by == "testid":
        return page.get_by_test_id(locator.value)
    return page.locator("css=" + locator.value)


class ToolExecutor:
    def __init__(self, target: Target, run: Run, policy: TargetPolicy):
        self.target, self.run, self.policy = target, run, policy
        self.redact = Redactor(target)
        self.clients, self.contexts, self.pages = {}, {}, {}
        self.driver = self.browser = None
        self.namespace = uuid.uuid4().hex
        self.allow_mutations = False
        self.current_action = "setup"
        self.current_contract = ""
        self.blocks = []
        self.response_tasks = []
        self.network_budget = 300
        self.started = time.monotonic()

    def headers(self, actor):
        headers = secret_headers(self.target, actor)
        if self.target.namespace_header:
            if self.target.namespace_header.lower() in {k.lower() for k in headers}:
                raise PolicyError("Identity cannot override the sandbox namespace")
            headers[self.target.namespace_header] = self.namespace
        return headers

    async def request(self, actor: str, method: str, url: str, body=None):
        if method not in {"GET", "HEAD"} and not self.allow_mutations:
            raise PolicyError("This write requires explicit action approval")
        if actor not in self.clients:
            from urllib.parse import urlsplit
            from .network import PinnedTransport
            transport = PinnedTransport(urlsplit(self.policy.base_origin).hostname, self.policy.pinned_ip) if self.policy.pinned_ip else None
            self.clients[actor] = httpx.AsyncClient(headers=self.headers(actor), transport=transport, timeout=10, trust_env=False, follow_redirects=False)
        for _ in range(5):
            self.network_budget -= 1
            if self.network_budget < 0:
                raise PolicyError("Network request budget exhausted")
            checked = self.policy.validate(url)
            async with self.clients[actor].stream(method, checked, json=body) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 131072:
                        raise PolicyError("HTTP response exceeds 128 KiB")
                if response.status_code in {301, 302, 303, 307, 308}:
                    # Do not silently turn a mutating redirect into a GET.
                    if method not in {"GET", "HEAD"}:
                        raise PolicyError("Mutating redirects require a new reviewed action")
                    from urllib.parse import urljoin
                    url = self.policy.validate(urljoin(checked, response.headers.get("location", "")))
                    continue
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeDecodeError):
                    payload = {"text": data.decode("utf-8", errors="replace")[:16000]}
                return {"status": response.status_code, "body": payload, "url": checked, "method": method}
        raise PolicyError("Redirect budget exhausted")

    async def page(self, actor: str):
        if actor in self.pages:
            return self.pages[actor]
        if self.browser is None:
            from playwright.async_api import async_playwright
            try:
                self.driver = await async_playwright().start()
            except NotImplementedError as exc:
                raise RuntimeError('Browser subprocess is unavailable on this event loop. On Windows start the service without --reload or multiple workers.') from exc
            args = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--disable-quic", "--no-proxy-server"]
            if self.policy.pinned_ip:
                from urllib.parse import urlsplit
                args.append(f'--host-resolver-rules=MAP {urlsplit(self.policy.base_origin).hostname} {self.policy.pinned_ip}')
            self.browser = await self.driver.chromium.launch(headless=True, args=args)
        context = await self.browser.new_context(extra_http_headers=self.headers(actor), service_workers="block", accept_downloads=False, viewport={"width":1200,"height":800})

        async def gate(route):
            request = route.request
            try:
                self.policy.validate(request.url)
                self.network_budget -= 1
                if self.network_budget < 0:
                    raise PolicyError("Network request budget exhausted")
                if request.method not in {"GET", "HEAD", "OPTIONS"} and not self.allow_mutations:
                    raise PolicyError("Browser write has no action approval")
                await route.continue_()
            except (ValueError, TypeError) as exc:
                self.blocks.append(self.redact(str(exc)))
                await route.abort("blockedbyclient")

        await context.route("**/*", gate)
        await context.route_web_socket("**/*", lambda socket: socket.close())
        page = await context.new_page()
        page.set_default_timeout(4000)
        page.on("dialog", lambda dialog: dialog.dismiss())

        def response_received(response):
            action_id, contract_id = self.current_action, self.current_contract
            task = asyncio.create_task(self.record_response(response, action_id, contract_id))
            self.response_tasks.append(task)

        page.on("response", response_received)
        self.contexts[actor], self.pages[actor] = context, page
        await page.goto(self.policy.validate(self.target.base_url), wait_until="domcontentloaded")
        return page

    def evidence(self, source_type: str, value, action_id: str, *, ok=True, error=None, artifact=None, contract_id=None, **provenance):
        evidence = Evidence(run_id=self.run.id, contract_id=contract_id or self.current_contract, action_id=action_id, source_type=source_type,
                            observed_value=self.redact(value), artifact_reference=artifact,
                            provenance=self.redact({"executor":"yanzhen.verifyagent.ToolExecutor/v1", "ok":ok, "error":error, "namespace":self.namespace, **provenance})).seal()
        self.run.evidence.append(evidence)
        return evidence

    async def record_response(self, response, action_id, contract_id):
        try:
            checked = self.policy.validate(response.url)
            if response.request.resource_type not in {"fetch", "xhr", "document"}:
                return
            value = {"url":checked, "method":response.request.method, "status":response.status}
            length = response.headers.get("content-length")
            if length and int(length) <= 32768 and "json" in response.headers.get("content-type", ""):
                value["body"] = await response.json()
            self.evidence("http_response", value, action_id, contract_id=contract_id)
        except Exception:
            # An auxiliary network capture cannot erase a completed deterministic probe.
            return

    async def observe(self, actor="anonymous"):
        if self.target.interface == "api":
            result = await self.request(actor, "GET", self.target.base_url)
            value = self.redact({"api_entry":result,"actors":["anonymous", *self.target.identities]})
            self.evidence("api_snapshot", value, "observe")
            return value
        page = await self.page(actor)
        # Browser-generated descriptors only; no arbitrary script is accepted from a planner.
        elements = await page.locator("button, a, input, textarea, select, [data-testid], [role=status]").evaluate_all("els => els.slice(0,60).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),text:(e.innerText||'').slice(0,120),label:e.getAttribute('aria-label')||Array.from(e.labels||[]).map(l=>l.innerText).join(' ').slice(0,120),placeholder:e.getAttribute('placeholder'),testid:e.getAttribute('data-testid'),type:e.type,name:e.name,href:e.getAttribute('href')}))")
        text = (await page.locator("body").inner_text())[:10000]
        value = self.redact({"url":page.url, "text":text, "elements":elements, "actors":["anonymous", *self.target.identities], "network_blocks":self.blocks[-5:]})
        self.evidence("page_snapshot", value, "observe")
        return value

    @staticmethod
    def needs_approval(action: Action):
        # Click/fill/select may trigger autosave or form submissions in unknown applications.
        return action.kind in {"click", "fill", "select"} or (action.kind == "http_request" and action.method not in {"GET", "HEAD"})

    async def act(self, action: Action, approved=False):
        self.current_action = action.id
        self.allow_mutations = approved
        before_blocks = len(self.blocks)
        started = time.monotonic()
        value, error, ok, artifact = None, None, False, None
        try:
            for attempt in range(action.retries + 1):
                try:
                    async with asyncio.timeout(action.timeout_ms / 1000 + 1):
                        value = await self._act(action)
                    break
                except Exception:
                    if attempt == action.retries:
                        raise
            if len(self.blocks) > before_blocks:
                raise PolicyError(self.blocks[-1])
            ok = True
        except Exception as exc:
            error = {"type":type(exc).__name__, "message":self.redact(str(exc))[:600], "category":"policy" if isinstance(exc, PolicyError) else "tool"}
        finally:
            self.allow_mutations = False
        if self.response_tasks:
            pending, self.response_tasks = self.response_tasks, []
            await asyncio.gather(*pending, return_exceptions=True)
        page = self.pages.get(action.actor)
        if page:
            try:
                directory = path("runs", self.run.id)
                directory.mkdir(parents=True, exist_ok=True)
                artifact = "screen-" + uuid.uuid4().hex + ".png"
                masks = [page.locator("input[type=password], [data-sensitive]")]
                masks.extend(page.get_by_text(secret, exact=False) for secret in self.redact.values if len(secret) >= 6)
                await page.screenshot(path=str(directory / artifact), mask=masks, timeout=3000)
            except Exception:
                artifact = None
        observation = self.evidence("tool_result", value, action.id, ok=ok, error=error, artifact=artifact, action_digest=digest(action))
        row = {"contract_id":self.current_contract, "action":self.redact(action.model_dump(mode="json")), "action_digest":digest(action), "ok":ok,
               "observed_value":observation.observed_value,
               "error":error, "evidence_id":observation.evidence_id, "duration_ms":round((time.monotonic()-started)*1000), "timestamp":now()}
        self.run.trace.append(row)
        return row

    async def _act(self, a: Action):
        if a.kind == "http_request":
            return await self.request(a.actor, a.method, a.url, a.json_body)
        if a.kind in {"assert_status", "assert_json", "compare_state"}:
            if not isinstance(a.value, dict):
                raise ValueError("Assertion tool parameters must be a JSON object")
            if a.kind == "compare_state":
                def measured(name):
                    return next(e.observed_value for e in reversed(self.run.evidence) if e.contract_id == self.current_contract and e.provenance.get("probe_id") == name and e.provenance.get("ok"))
                left, right = measured(a.value["left_probe"]), measured(a.value["right_probe"])
                return {"left":left,"right":right,"equal":type(left) is type(right) and left == right}
            row = next(x for x in reversed(self.run.trace) if x["contract_id"] == self.current_contract and x["action"]["id"] == a.value["action_id"] and x["ok"])
            observed = next(e.observed_value for e in self.run.evidence if e.evidence_id == row["evidence_id"])
            actual = observed["status"] if a.kind == "assert_status" else json_pointer(observed["body"], a.value.get("pointer", ""))
            return {"actual":actual,"expected":a.value["expected"],"matches":type(actual) is type(a.value["expected"]) and actual == a.value["expected"]}
        page = await self.page(a.actor)
        if a.kind == "navigate":
            response = await page.goto(self.policy.validate(a.url), wait_until="domcontentloaded", timeout=a.timeout_ms)
            return {"url":page.url,"status":response.status if response else None}
        if a.kind == "reload":
            response = await page.reload(wait_until="domcontentloaded", timeout=a.timeout_ms)
            return {"url":page.url,"status":response.status if response else None}
        locator = locate(page, a.locator)
        if a.kind == "click":
            await locator.click(timeout=a.timeout_ms)
        elif a.kind == "fill":
            await locator.fill(str(a.value), timeout=a.timeout_ms)
        elif a.kind == "select":
            await locator.select_option(str(a.value), timeout=a.timeout_ms)
        elif a.kind in {"wait_for", "assert_visible"}:
            await locator.wait_for(state="visible", timeout=a.timeout_ms)
        elif a.kind == "assert_text":
            return {"text":await locator.inner_text(timeout=a.timeout_ms)}
        return {"action_completed":True}

    async def probe(self, probe: Probe):
        try:
            if probe.source_type.startswith("http_"):
                result = await self.request(probe.actor, "GET", probe.url)
                if result['status']>=500:
                    raise RuntimeError('Target dependency is unavailable: HTTP '+str(result['status']))
                value = result["status"] if probe.source_type == "http_status" else json_pointer(result["body"], probe.pointer)
            else:
                page = await self.page(probe.actor)
                await page.wait_for_load_state("networkidle", timeout=4000)
                locator = locate(page, probe.locator)
                value = await locator.is_visible() if probe.source_type == "dom_visible" else await locator.inner_text(timeout=4000)
            return self.evidence(probe.source_type, value, self.current_action, probe_id=probe.id, phase=probe.phase)
        except Exception as exc:
            return self.evidence(probe.source_type, None, self.current_action, ok=False, error={"type":type(exc).__name__,"message":self.redact(str(exc))[:400]}, probe_id=probe.id, phase=probe.phase)

    async def close(self):
        for client in self.clients.values():
            await client.aclose()
        if self.browser:
            await self.browser.close()
        if self.driver:
            await self.driver.stop()
