"""Isolated, deliberately configurable reimbursement fixture. Never a production API."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .store import load_run, run_dir
from .settings import ROOT

router = APIRouter(prefix="/demo")
USERS = {"alice", "bob", "admin"}


def connect(run_id: str):
    path = run_dir(run_id) / "demo.sqlite"
    if not path.exists():
        raise HTTPException(404, "演示环境不存在")
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def seed(run_id: str) -> None:
    path = run_dir(run_id) / "demo.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY, owner TEXT, amount INTEGER, status TEXT, note TEXT);
            CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, username TEXT);
            INSERT INTO records VALUES (1,'alice',120,'approved','已审批的交通费');
            INSERT INTO records VALUES (2,'alice',85,'draft','待补充的餐费说明');
            INSERT INTO records VALUES (3,'bob',260,'draft','Bob 的会议费用');
        """)


def scenario(run_id: str) -> str:
    try:
        value = load_run(run_id).scenario
    except FileNotFoundError:
        raise HTTPException(404, "演示环境不存在")
    if value == "environment_down":
        raise HTTPException(503, "受控演示：服务不可用")
    return value


def identity(run_id: str, authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请登录演示账号")
    token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with connect(run_id) as db:
        row = db.execute("SELECT username FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
    if not row:
        raise HTTPException(401, "演示会话无效")
    return row["username"]


class Login(BaseModel):
    username: str


class Note(BaseModel):
    note: str = Field(min_length=1, max_length=500)


@router.get("/{run_id}", response_class=HTMLResponse)
def page(run_id: str):
    scenario(run_id)
    text = (ROOT / "yanzhen" / "web" / "demo.html").read_text(encoding="utf-8")
    return text.replace("__RUN_ID__", run_id).replace("__SAVE_LABEL__", "更新报销说明" if scenario(run_id) == "locator_drift" else "保存说明")


@router.post("/{run_id}/api/login")
def login(run_id: str, request: Login):
    scenario(run_id)
    if request.username not in USERS:
        raise HTTPException(401, "仅支持内置演示账号")
    token = secrets.token_urlsafe(32)
    with connect(run_id) as db:
        db.execute("INSERT INTO sessions VALUES (?,?)", (hashlib.sha256(token.encode()).hexdigest(), request.username))
    return {"token": token, "username": request.username, "fixture_only": True}


@router.get("/{run_id}/api/records")
def list_records(run_id: str, authorization: str | None = Header(default=None)):
    scenario(run_id)
    user = identity(run_id, authorization)
    with connect(run_id) as db:
        rows = db.execute("SELECT * FROM records" if user == "admin" else "SELECT * FROM records WHERE owner=?", () if user == "admin" else (user,)).fetchall()
    return {"records": [dict(row) for row in rows]}


@router.get("/{run_id}/api/records/{record_id}")
def get_record(run_id: str, record_id: int, authorization: str | None = Header(default=None)):
    variant = scenario(run_id)
    user = identity(run_id, authorization)
    with connect(run_id) as db:
        row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "记录不存在")
    # This is the controlled ownership defect being measured.
    if user != "admin" and row["owner"] != user and variant not in {"auth_bug", "broken"}:
        raise HTTPException(403, "不能读取其他成员的记录")
    return dict(row)


@router.post("/{run_id}/api/records/{record_id}/submit")
def submit(run_id: str, record_id: int, authorization: str | None = Header(default=None)):
    variant = scenario(run_id)
    user = identity(run_id, authorization)
    with connect(run_id) as db:
        row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "记录不存在")
        if row["owner"] != user:
            raise HTTPException(403, "不能修改其他成员的记录")
        if row["status"] != "draft" and variant not in {"state_bug", "broken"}:
            raise HTTPException(409, "已审批记录不可重复提交")
        db.execute("UPDATE records SET status='submitted' WHERE id=?", (record_id,))
    return {"id": record_id, "status": "submitted"}


@router.patch("/{run_id}/api/records/{record_id}")
def save_note(run_id: str, record_id: int, request: Note, authorization: str | None = Header(default=None)):
    variant = scenario(run_id)
    user = identity(run_id, authorization)
    with connect(run_id) as db:
        row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "记录不存在")
        if row["owner"] != user:
            raise HTTPException(403, "不能修改其他成员的记录")
        if variant not in {"persistence_bug", "broken"}:
            db.execute("UPDATE records SET note=? WHERE id=?", (request.note, record_id))
    return {"success": True, "id": record_id, "note": request.note}
