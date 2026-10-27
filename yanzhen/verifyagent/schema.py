from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..models import now


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Locator(Strict):
    by: Literal["role", "label", "placeholder", "testid", "css"]
    value: str = Field(min_length=1, max_length=250)
    role: str = Field(default="button", max_length=40)


ActionKind = Literal["navigate", "click", "fill", "select", "wait_for", "assert_visible", "assert_text", "http_request", "assert_status", "assert_json", "reload", "compare_state"]


class Action(Strict):
    """Closed DSL. Assertions here are tool observations; only frozen predicates decide PASS."""
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    kind: ActionKind
    actor: str = Field(default="anonymous", pattern=r"^[A-Za-z0-9_-]{1,40}$")
    locator: Locator | None = None
    url: str | None = Field(default=None, max_length=2000)
    value: Any = None
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    json_body: dict | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    timeout_ms: int = Field(default=4000, ge=100, le=10000)
    retries: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def bounded(self):
        if self.kind in {"click", "fill", "select", "wait_for", "assert_visible", "assert_text"} and not self.locator:
            raise ValueError("This action requires a structured locator")
        if self.kind in {"navigate", "http_request"} and not self.url:
            raise ValueError("This action requires a URL")
        if self.kind != "http_request" and (self.method != "GET" or self.json_body is not None):
            raise ValueError("HTTP parameters belong only to http_request")
        if self.retries and self.kind in {"click", "fill", "select"}:
            raise ValueError("Mutating actions must not be automatically retried")
        if self.retries and self.method not in {"GET", "HEAD"}:
            raise ValueError("Mutating requests must not be automatically retried")
        if len(json.dumps(self.value, ensure_ascii=False)) > 4000 or len(json.dumps(self.json_body)) > 16000:
            raise ValueError("Action payload exceeds the limit")
        return self


class Probe(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    source_type: Literal["dom_text", "dom_visible", "http_status", "http_json"]
    phase: Literal["before", "after", "always", "checkpoint"] = "after"
    after_action: ActionKind | None = Field(default=None, description='Checkpoint trigger only. Other phases ignore this field: before runs once initially, after runs once when planning finishes, always runs at each boundary.')
    actor: str = "anonymous"
    locator: Locator | None = None
    url: str | None = None
    pointer: str = Field(default='',description='RFC 6901 JSON Pointer: /note or /items/0/name. Never use a bare field name, JSONPath or code. Empty means the whole JSON value.')

    @model_validator(mode="after")
    def executable(self):
        if self.phase == "checkpoint" and self.after_action is None:
            raise ValueError("Checkpoint probes require a triggering action kind")
        if self.source_type.startswith("dom_") and not self.locator:
            raise ValueError("DOM probe requires a locator")
        if self.source_type.startswith("http_") and not self.url:
            raise ValueError("HTTP probe requires a URL")
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("Use RFC 6901 JSON Pointer, not executable expressions")
        return self


class Source(Strict):
    quote: str = Field(min_length=1, max_length=4000,description='An exact contiguous span of ORIGINAL REQUIREMENTS, never page/discovery text. Derived setup conditions still cite the relevant requirement and use basis=assumption.')
    basis: Literal["direct", "assumption"] = "direct"
    explanation: str = Field(default="", max_length=1000)


class Predicate(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    left: str
    op: Literal["eq", "ne", "contains", "not_contains", "in", "not_in", "gte", "lte"] = "eq"
    expected: Any = None
    right_probe: str | None = None
    source: Source


class RequiredOperation(Strict):
    kind: ActionKind
    actor: str | None = None
    method: str | None = None
    url: str | None = None
    value: Any = None
    json_body: dict | None = None

    @model_validator(mode='after')
    def meaningful(self):
        if self.value is not None and self.kind not in {'fill','select'}:
            raise ValueError('required_operations.value is only a typed fill/select input, not a click label; button names belong in execution locators')
        return self


class Constraints(Strict):
    required_actions: list[ActionKind] = Field(default_factory=list)
    forbidden_actions: list[ActionKind] = Field(default_factory=list)
    required_operations: list[RequiredOperation] = Field(default_factory=list, max_length=30)
    max_steps: int = Field(default=24, ge=1, le=60)


class GenericContract(Strict):
    """C = (preconditions, action constraints, postconditions, invariants, sources)."""
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    title: str = Field(min_length=1, max_length=160)
    probes: list[Probe] = Field(min_length=1, max_length=30)
    preconditions: list[Predicate] = Field(default_factory=list, max_length=30)
    constraints: Constraints = Field(default_factory=Constraints)
    postconditions: list[Predicate] = Field(min_length=1, max_length=30)
    invariants: list[Predicate] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def references(self):
        probes = {p.id: p for p in self.probes}
        predicates = self.preconditions + self.postconditions + self.invariants
        if len(probes) != len(self.probes) or len({p.id for p in predicates}) != len(predicates):
            raise ValueError("Probe and predicate identifiers must be unique")
        for assertion in predicates:
            if assertion.left not in probes or (assertion.right_probe and assertion.right_probe not in probes):
                raise ValueError("Predicate refers to an undefined probe")
        for assertion in self.preconditions:
            if probes[assertion.left].phase != "before":
                raise ValueError("Preconditions require before probes")
        # Transient requirements (e.g. a save acknowledgement) legitimately refer
        # to a checkpoint. They must never replace a final business observation.
        for assertion in self.postconditions:
            if probes[assertion.left].phase == "before":
                raise ValueError("Postconditions cannot rely only on a before probe")
        if not any(probes[a.left].phase in {"after", "always"} for a in self.postconditions):
            raise ValueError("Postconditions require at least one independent final observation; checkpoints alone cannot establish acceptance")
        for assertion in self.invariants:
            if probes[assertion.left].phase != "always":
                raise ValueError("Invariants require an always probe")
        return self


class ContractSet(Strict):
    contracts: list[GenericContract] = Field(default_factory=list, max_length=15)
    clarification_questions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.contracts and not self.clarification_questions:
            raise ValueError('Provide contracts or explicit clarification questions')
        return self


class Bundle(ContractSet):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    requirements: str = Field(min_length=5, max_length=16000)
    target_id: str
    provider: Literal["manual", "qwen", "deepseek", "jiuwenswarm", "openjiuwen"]
    version: int = Field(default=1, ge=1)
    parent_id: str | None = None
    frozen: bool = False
    digest: str = ""
    created_at: str = Field(default_factory=now)
    reviewed_by: str | None = None
    usage: dict = Field(default_factory=dict)
    discovery: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def sources(self):
        if len({c.id for c in self.contracts}) != len(self.contracts):
            raise ValueError("Contract identifiers must be unique")
        for contract in self.contracts:
            for p in contract.preconditions + contract.postconditions + contract.invariants:
                if p.source.quote not in self.requirements:
                    raise ValueError("Every assertion must cite a verbatim requirement span")
        return self

    def calculate_digest(self):
        payload=self.model_dump(exclude={"frozen", "digest", "created_at", "reviewed_by", "usage"})
        if not self.discovery:payload.pop('discovery',None)  # Preserve earlier frozen v2 snapshots.
        return digest(payload)

    def assert_frozen(self):
        if not self.frozen or self.digest != self.calculate_digest():
            raise ValueError("Contract is not frozen or its semantics were changed")


class Identity(Strict):
    # Values are environment variable names. Credentials never enter API requests or archives.
    header_env: dict[str, str] = Field(default_factory=dict)


class Target(Strict):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    project_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    interface: Literal["web", "api"] = "web"
    api_description_urls: list[str] = Field(default_factory=list,max_length=3)
    environment: Literal["local", "test"]
    authorized: bool
    identities: dict[str, Identity] = Field(default_factory=dict)
    namespace_header: str | None = Field(default=None, pattern=r"^X-[A-Za-z0-9-]{1,60}$")
    isolation_note: str = Field(default="Browser/API sessions are isolated; backend state is not reset.", max_length=1000)


class Evidence(Strict):
    evidence_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    contract_id: str
    action_id: str
    source_type: str
    observed_value: Any
    timestamp: str = Field(default_factory=now)
    provenance: dict
    artifact_reference: str | None = None
    content_hash: str = ""

    def seal(self):
        self.content_hash = digest(self.model_dump(exclude={"content_hash"}))
        return self


class Decision(Strict):
    action: Action | None = None
    finished: bool = False
    explanation: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def choice(self):
        if self.finished == (self.action is not None):
            raise ValueError("Choose exactly one action or finished=true")
        return self


class RunInput(Strict):
    bundle_id: str
    planner: Literal["manual", "qwen", "deepseek", "jiuwenswarm", "openjiuwen"]
    manual_actions: list[Action] = Field(default_factory=list, max_length=60)
    candidate_target_id: str | None = None
    parent_run: str | None = None
    max_model_calls: int = Field(default=30, ge=1, le=60)
    max_seconds: int = Field(default=180, ge=5, le=600)

    @model_validator(mode="after")
    def explicit_manual(self):
        if self.planner != "manual" and self.manual_actions:
            raise ValueError("Manual actions cannot masquerade as autonomous model planning")
        return self


class Run(Strict):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    bundle_id: str
    target_id: str
    contract_digest: str
    planner: str
    status: Literal["queued", "running", "waiting_approval", "completed", "cancelled", "error"] = "queued"
    created_at: str = Field(default_factory=now)
    finished_at: str | None = None
    events: list[dict] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    results: list[dict] = Field(default_factory=list)
    graph: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})
    usage: dict = Field(default_factory=dict)
    pending_approval: dict | None = None
    approvals: list[dict] = Field(default_factory=list)
    parent_run: str | None = None
    error: str | None = None
    reproductions: list[dict] = Field(default_factory=list)
