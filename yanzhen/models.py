from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    UNCLEAR = "unclear"


CATALOG = {
    "own_record": {"title": "成员可读取本人报销单", "role": "alice", "expected": "allowed", "group": "权限"},
    "foreign_record": {"title": "成员不能读取他人报销单", "role": "alice", "expected": "denied", "group": "权限"},
    "admin_record": {"title": "管理员可读取全部报销单", "role": "admin", "expected": "allowed", "group": "权限"},
    "approved_locked": {"title": "已审批报销单不能再次提交", "role": "alice", "expected": "rejected_without_change", "group": "状态流转"},
    "save_persists": {"title": "保存的说明在刷新后保持一致", "role": "alice", "expected": "persisted", "group": "数据保存"},
}

DEFAULT_REQUIREMENTS = """普通成员只能查看本人的报销单，不能读取其他成员的报销单。
管理员可以查看全部成员的报销单。
已经审批通过的报销单不能再次提交，拒绝操作后状态保持已审批。
成员修改并保存本人报销说明后，刷新页面或重新查询仍能看到修改后的内容。"""


REIMBURSEMENT_KINDS = frozenset(CATALOG)
CATALOG.update({
    "todo_add": {"title": "新增任务后列表显示该任务", "role": "local_user", "expected": "visible", "group": "任务管理"},
    "todo_complete": {"title": "任务标记完成后出现在已完成列表", "role": "local_user", "expected": "completed_visible", "group": "任务管理"},
    "todo_persists": {"title": "新增任务刷新后仍然存在", "role": "local_user", "expected": "persisted", "group": "数据保存"},
})
TODO_REQUIREMENTS = "新增任务后列表显示该任务。任务标记完成后出现在已完成列表。新增任务刷新后仍然存在。"
TODO_SCENARIOS = {"upstream": "TodoMVC 上游原版（内存存储）", "healthy": "本地持久化修复对照版", "environment_down": "模拟资源不可用"}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,50}$")
    kind: str
    title: str = Field(min_length=1, max_length=150)
    source_quote: str = Field(min_length=1, max_length=4000)
    role: str
    expected: str
    rationale: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.kind == "unclear":
            if self.role != "unknown" or self.expected != "needs_clarification":
                raise ValueError("不明确需求必须使用 unknown / needs_clarification")
        elif self.kind not in CATALOG:
            raise ValueError("首版执行器不支持这个检查类型")
        elif any(getattr(self, key) != CATALOG[self.kind][key] for key in ("role", "expected")):
            raise ValueError("角色或预期与受支持的验收契约不一致")
        return self


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    requirements: str
    provider: Literal["offline", "qwen"]
    model: str | None = None
    contracts: list[Contract] = Field(min_length=1, max_length=30)
    created_at: str = Field(default_factory=now)
    frozen: bool = False
    digest: str = ""
    usage: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def verify_sources(self):
        ids = [c.id for c in self.contracts]
        kinds = [c.kind for c in self.contracts if c.kind != "unclear"]
        if len(ids) != len(set(ids)) or len(kinds) != len(set(kinds)):
            raise ValueError("契约编号或可执行检查重复")
        if any(c.source_quote not in self.requirements for c in self.contracts):
            raise ValueError("每个契约必须引用需求中的真实原文")
        return self

    def calculate_digest(self) -> str:
        payload = self.model_dump(exclude={"frozen", "digest", "usage", "created_at"})
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def assert_frozen(self) -> None:
        if not self.frozen or self.digest != self.calculate_digest():
            raise ValueError("验收契约尚未冻结或内容已被更改")


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirements: str = Field(min_length=5, max_length=16000)
    provider: Literal["offline", "qwen"] = "offline"
    target: Literal["reimbursement", "todomvc"] = "reimbursement"


SCENARIOS = {
    "healthy": "正确实现",
    "broken": "三类缺陷同时存在",
    "auth_bug": "接口缺少归属检查",
    "state_bug": "已审批记录仍可提交",
    "persistence_bug": "保存提示成功但未写入",
    "locator_drift": "按钮改名，业务功能正确",
    "environment_down": "模拟服务不可用",
}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    target: str = Field(default="reimbursement", pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    scenario: Literal["healthy", "broken", "auth_bug", "state_bug", "persistence_bug", "locator_drift", "environment_down", "upstream"] = "broken"
    browser: bool = True


class Evidence(BaseModel):
    id: str
    kind: Literal["http", "screenshot", "observation", "repair"]
    description: str
    data: dict = Field(default_factory=dict)
    file: str | None = None


class CheckResult(BaseModel):
    contract_id: str
    kind: str
    title: str
    verdict: Verdict
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    replay_steps: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    conflicts: list[dict] = Field(default_factory=list)


class Run(BaseModel):
    id: str
    bundle_id: str
    digest: str
    scenario: str
    browser_requested: bool
    target: str = "reimbursement"
    status: Literal["queued", "running", "finalizing", "completed", "error", "cancelled"] = "queued"
    created_at: str = Field(default_factory=now)
    finished_at: str | None = None
    parent_run: str | None = None
    results: list[CheckResult] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    error: str | None = None
    internal_trial: bool = False
    reproductions: list[dict] = Field(default_factory=list)
    target_source: dict = Field(default_factory=dict)

    def summary(self) -> dict:
        return {v.value: sum(r.verdict == v for r in self.results) for v in Verdict}
