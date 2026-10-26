"""Authorized disposable test application. Defects live here, never in the verifier."""
from __future__ import annotations

import re
import threading

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="VerifyAgent disposable orders / notes fixture", version="1.0")
from .holdout import router as inventory_router
app.include_router(inventory_router)
states = {}
lock = threading.RLock()
VARIANTS = {"healthy", "auth_bug", "persistence_bug", "both", "drift", "live_drift"}


def setup(variant, request):
    if variant not in VARIANTS:
        raise HTTPException(404)
    namespace = request.headers.get("X-Verify-Sandbox", "")
    if not re.fullmatch(r"[a-f0-9]{32}", namespace):
        raise HTTPException(400, "An isolated test namespace is required")
    with lock:
        return states.setdefault((variant, namespace), {"note":"", "orders":{"1":{"id":1,"owner":"alice"},"2":{"id":2,"owner":"bob"}}})


def actor(request):
    role = {"fixture-alice-credential":"alice", "fixture-bob-credential":"bob"}.get(request.headers.get("X-Test-Actor"))
    if not role:
        raise HTTPException(401,"Test identity is required")
    return role


@app.get("/app/{variant}/api/schema")
def schema(variant: str, request: Request):
    setup(variant, request)
    return {"application_version":"1.0", "paths":{"own_order":"api/orders/1","other_order":"api/orders/2","note":"api/note"},
            "method_notes":{"GET":"read current note","PATCH":{"note":"new text"}},"roles":["alice","bob"]}


@app.get("/app/{variant}/api/orders/{identifier}")
def order(variant: str, identifier: str, request: Request):
    state = setup(variant, request)
    role = actor(request)
    if identifier not in state["orders"]:
        raise HTTPException(404)
    result = state["orders"][identifier]
    if result["owner"] != role and variant not in {"auth_bug", "both"}:
        raise HTTPException(403,"Order belongs to a different user")
    return result


class Note(BaseModel):
    note: str = Field(max_length=500)


@app.get("/app/{variant}/api/note")
def read_note(variant: str, request: Request):
    return {"note":setup(variant, request)["note"]}


@app.patch("/app/{variant}/api/note")
def write_note(variant: str, request: Request, note: Note):
    state = setup(variant, request)
    if variant not in {"persistence_bug", "both"}:
        state["note"] = note.note
    return {"saved":True,"note":note.note}


@app.get("/app/{variant}/", response_class=HTMLResponse)
def page(variant: str, request: Request):
    setup(variant, request)
    button = "应用更改" if variant == "drift" else "保存"
    html = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Orders & notes test app</title>
<style>body{font:16px system-ui;max-width:650px;margin:80px auto;padding:30px;color:#26343e}input,button{padding:12px;font:inherit}label{display:block;margin-bottom:12px}output{display:block;padding:20px;background:#f1f6f7;margin-top:20px}</style>
<h1>测试工作空间</h1><p>这是经过授权、按运行隔离数据的测试应用。</p><label>备注 <input aria-label="备注" id="note"></label>
<button id="save">""" + button + """</button><p>当前内容：<span data-testid="readback"></span></p><div id="status" role="status"></div>
<a href="api/schema">API 描述</a><script>
const note=document.querySelector('#note'),readback=document.querySelector('[data-testid=readback]');
fetch('api/note').then(r=>r.json()).then(d=>{note.value=d.note;readback.textContent=d.note});
document.querySelector('#save').onclick=async()=>{const r=await fetch('api/note',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:note.value})});
const d=await r.json();if(d.saved){readback.textContent=note.value;document.querySelector('#status').textContent='保存成功';let o=document.querySelector('[data-testid=saved]');if(!o){o=document.createElement('output');o.dataset.testid='saved';document.body.append(o)}o.textContent=note.value}};
</script></html>"""
    if variant=='live_drift':
        # A real DOM replacement after a locator has been chosen. The replacement
        # retains the same business handler; only the execution detail changes.
        html=html.replace('</script>',"document.querySelector('#save').addEventListener('pointerenter',function(){const replacement=this.cloneNode(true);replacement.textContent='应用更改';replacement.onclick=this.onclick;this.replaceWith(replacement)},{once:true});</script>")
    return html
