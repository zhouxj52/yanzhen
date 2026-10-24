from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .settings import ROOT
from .store import load_run

router = APIRouter()
FILES = frozenset({"index.html","app.js","view.js","controller.js","model.js","store.js","template.js","helpers.js","app.css","LICENSE"})


@router.get("/targets/todomvc/{run_id}/{filename}")
def resource(run_id: str, filename: str):
    run = load_run(run_id)
    if run.target != "todomvc" or filename not in FILES:
        raise HTTPException(404)
    if run.scenario == "environment_down":
        raise HTTPException(503, "受控资源不可用")
    source = (ROOT / "yanzhen" / "web" / "todomvc" / filename).read_text(encoding="utf-8")
    if filename == "store.js" and run.scenario == "healthy":
        # Explicit local repair variant; never described as unmodified upstream.
        source = source.replace("let memoryStorage = {};", "let memoryStorage = new Proxy({}, {get:(_,key)=>localStorage.getItem(key), set:(_,key,value)=>{localStorage.setItem(key,value);return true;}});")
        source = source.replace("let uniqueID = 1;", "let uniqueID = Date.now();")
    if filename == "app.css":
        source += """body{font:16px/1.6 system-ui,sans-serif;background:#f5f6fa;color:#30394d;margin:60px auto;max-width:620px;padding:20px}h1{font-size:56px;color:#8780b9;font-weight:200;text-align:center}.todoapp{background:white;padding:24px;border-radius:10px;border:1px solid #e5e7ef}.new-todo{box-sizing:border-box;width:100%;padding:16px;font-size:20px;border:1px solid #ddd;border-radius:6px}.todo-list{list-style:none;padding:0}.todo-list li{border-bottom:1px solid #eee;padding:12px;font-size:20px}.view{display:flex;align-items:center;gap:12px}.view label{flex:1}.completed label{text-decoration:line-through;color:#999}.destroy{border:0;background:none;color:#b77}.destroy:after{content:'×'}.edit{display:none}.editing .edit{display:block}.editing .view{display:none}.filters{display:flex;gap:18px;list-style:none;padding:0}.filters a{color:#78729f}.info{font-size:12px;color:#999;text-align:center}.footer{font-size:13px}.toggle-all-container{padding:10px 0}"""
    media = "text/javascript" if filename.endswith(".js") else "text/css" if filename.endswith(".css") else "text/html" if filename.endswith(".html") else "text/plain"
    return Response(source, media_type=media, headers={"Cache-Control":"no-store"})
