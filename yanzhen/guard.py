from __future__ import annotations

from .models import Contract
from pydantic import BaseModel, ConfigDict, Field


class ExecutionPlan(BaseModel):
    """Closed action DSL; caller-supplied Python/JavaScript is never executed."""
    model_config = ConfigDict(extra="forbid")
    contract_id: str
    role: str
    action: str
    assertions: list[str] = Field(min_length=1)
    locator: str = Field(min_length=1, max_length=250)
    wait_ms: int = Field(default=0, ge=0, le=5000)
    skip: bool = False


def review_execution_repair(contract: Contract, original: ExecutionPlan, candidate: ExecutionPlan, witnessed_action: str) -> dict:
    violations = []
    if original.contract_id != contract.id or candidate.contract_id != contract.id:
        violations.append("契约编号改变")
    if original.role != contract.role or candidate.role != contract.role:
        violations.append("执行身份改变")
    if original.skip or candidate.skip:
        violations.append("跳过验收")
    if original.assertions != [contract.expected] or candidate.assertions != original.assertions:
        violations.append("断言被删除、替换或放宽")
    if not original.action or candidate.action != original.action or witnessed_action != original.action:
        violations.append("缺少同一业务动作的证据")
    if original.model_dump(exclude={"locator","wait_ms"}) != candidate.model_dump(exclude={"locator","wait_ms"}):
        violations.append("修改超出定位器和等待范围")
    return {"accepted":not violations,"contract_id":contract.id,"violations":violations,"scope":"仅结构审查受限执行计划；动作见证由调用方提供，不审查任意脚本或自动应用候选","original":original.model_dump(),"candidate":candidate.model_dump()}


def approve_locator_repair(original: Contract, candidate: Contract, *, action_before: str, action_after: str, witnessed_action: str) -> dict:
    """Only execution changes may be repaired; the frozen acceptance rule is invariant."""
    if original.model_dump() != candidate.model_dump():
        raise ValueError("拒绝修复：验收契约、角色或预期被更改")
    if not action_before or action_before != action_after or action_after != witnessed_action:
        raise ValueError("拒绝修复：缺少同一业务动作的证据")
    plan = ExecutionPlan(contract_id=original.id,role=original.role,action=action_before,assertions=[original.expected],locator="role=button[name=保存说明]")
    candidate_plan = plan.model_copy(update={"locator":"testid=save-note"})
    review = review_execution_repair(original,plan,candidate_plan,witnessed_action)
    if not review["accepted"]:
        raise ValueError("拒绝修复：" + "、".join(review["violations"]))
    return {**review, "unchanged_contract": True, "business_action": action_after}
