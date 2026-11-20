"""AI agent registry and orchestrator.

Each agent declares responsibilities, input/output JSON schemas, the tools (internal service functions)
it may call, the permission required to run it, and whether its output needs human approval before any
downstream action. All execution goes through `run_agent`, which validates input, records an
AgentExecution row (usage, duration, errors) and writes an audit log.

Policy: agents perform administrative assistance (organizing, proofreading, classifying, validating,
summarizing). No agent writes persuasive political messaging or profiles individuals.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.audit import audit
from app.core.db import session_scope
from app.core.errors import ValidationFailed
from app.models import AgentExecution
from app.services.ai.providers import get_provider
from app.services.text_checks import proofread


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": STR}


# ---------------------------------------------------------------- input models
class CalendarPlanInput(BaseModel):
    start_date: date
    end_date: date
    sends_per_week: int = Field(ge=1, le=7)
    themes: list[str] = Field(min_length=1, description="Approved campaign themes supplied by staff")
    blackout_dates: list[date] = []
    draft_lead_days: int = Field(default=5, ge=1, le=30)


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


class UnsubInput(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class ClassifyInput(BaseModel):
    items: list[str] = Field(min_length=1, max_length=200)
    categories: list[str] = Field(min_length=2, max_length=20)


# ---------------------------------------------------------------- deterministic fallbacks
WEEKDAY_PREF = [1, 3, 0, 2, 4, 5, 6]  # Tue, Thu, Mon, Wed, Fri, Sat, Sun


def plan_calendar(inp: CalendarPlanInput) -> dict[str, Any]:
    if inp.end_date < inp.start_date:
        raise ValidationFailed("end_date before start_date")
    days = WEEKDAY_PREF[: inp.sends_per_week]
    blackout = set(inp.blackout_dates)
    slots: list[dict[str, Any]] = []
    d, i = inp.start_date, 0
    while d <= inp.end_date:
        if d.weekday() in days and d not in blackout:
            slots.append(
                {
                    "send_date": d.isoformat(),
                    "theme": inp.themes[i % len(inp.themes)],
                    "draft_deadline": (d - timedelta(days=inp.draft_lead_days)).isoformat(),
                    "production_requirements": "Human-authored copy in Google Doc; reviewer sign-off; QA checks",
                }
            )
            i += 1
        d += timedelta(days=1)
    return {"slots": slots, "notes": [f"{len(slots)} sends planned; content must be supplied by staff."]}


EXPLICIT_UNSUB = re.compile(
    r"\b(unsubscribe|unsub|opt[\s-]?out|remove me|take me off|stop (emailing|texting|sending|contacting)|"
    r"do not (email|contact|text)|don'?t (email|contact|text)|cancel my subscription|^stop$|stopall|end|quit|cancel)\b",
    re.I | re.M,
)
AMBIGUOUS = re.compile(r"\b(too many|less (email|often)|annoying|spam|why am i getting|who gave)\b", re.I)


def classify_unsub(text: str) -> dict[str, Any]:
    t = text.strip()
    if EXPLICIT_UNSUB.search(t):
        return {"intent": "unsubscribe", "confidence": 0.99, "explicit": True, "rationale": "Explicit opt-out phrase"}
    if AMBIGUOUS.search(t):
        return {"intent": "unclear", "confidence": 0.5, "explicit": False, "rationale": "Possible opt-out sentiment"}
    return {"intent": "other", "confidence": 0.7, "explicit": False, "rationale": "No opt-out language detected"}


def extract_tasks(text: str) -> dict[str, Any]:
    tasks = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+[.)]|todo:|action:)\s*(.+)$", line, re.I)
        if m:
            due = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", line)
            tasks.append({"title": m.group(1).strip()[:200], "due_date": due.group(1) if due else ""})
    return {"tasks": tasks}


def summarize(text: str) -> dict[str, Any]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return {"summary": " ".join(sentences[:3])[:1200], "key_points": [s[:200] for s in sentences[:5] if s]}


def classify_items(inp: ClassifyInput) -> dict[str, Any]:
    out = []
    for item in inp.items:
        low = item.lower()
        cat = next((c for c in inp.categories if c.lower() in low), inp.categories[-1])
        out.append({"item": item, "category": cat, "needs_review": cat == inp.categories[-1]})
    return {"results": out}


# ---------------------------------------------------------------- registry
@dataclass
class AgentSpec:
    key: str
    name: str
    responsibilities: str
    permission: str
    input_model: type[BaseModel]
    output_schema: dict[str, Any]
    system_prompt: str
    fallback: Callable[[Any], dict[str, Any]]
    tools: list[str] = field(default_factory=list)
    requires_approval: bool = False
    use_llm: bool = True

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "responsibilities": self.responsibilities,
            "permission": self.permission, "requires_approval": self.requires_approval, "tools": self.tools,
            "input_schema": self.input_model.model_json_schema(), "output_schema": self.output_schema,
        }


POLICY = (
    "You assist agency staff with administrative work only. Never write persuasive political messaging, "
    "never infer political views or sensitive traits about individuals, and never fabricate facts. "
    "Return only JSON matching the schema."
)

AGENTS: dict[str, AgentSpec] = {
    a.key: a
    for a in [
        AgentSpec(
            key="email_calendar_planner",
            name="Email Calendar Planner",
            responsibilities="Organizes send dates, staff-supplied themes, draft deadlines and production requirements.",
            permission="email:write",
            input_model=CalendarPlanInput,
            output_schema=_schema({
                "slots": {"type": "array", "items": _schema({"send_date": STR, "theme": STR, "draft_deadline": STR, "production_requirements": STR})},
                "notes": STRS,
            }),
            system_prompt=POLICY + " Distribute the provided themes across the date range. Do not invent themes.",
            fallback=plan_calendar,
            tools=["calendar.create_slots"],
            requires_approval=True,
            use_llm=False,  # scheduling is deterministic; keeps dates exact
        ),
        AgentSpec(
            key="proofreader",
            name="Proofreader",
            responsibilities="Flags spelling, repeated words, spacing, accessibility and formatting issues in human-authored copy.",
            permission="email:read",
            input_model=TextInput,
            output_schema=_schema({"issues": {"type": "array", "items": _schema({"kind": STR, "excerpt": STR, "suggestion": STR})}}),
            system_prompt=POLICY + " Identify mechanical errors only; do not rewrite tone or argument.",
            fallback=lambda i: {"issues": proofread(i.text)},
        ),
        AgentSpec(
            key="unsubscribe_classifier",
            name="Unsubscribe Classifier",
            responsibilities="Classifies inbound replies for opt-out intent. Explicit requests are always honored by rules first.",
            permission="compliance:write",
            input_model=UnsubInput,
            output_schema=_schema({"intent": {"type": "string", "enum": ["unsubscribe", "unclear", "other"]}, "confidence": {"type": "number"}, "explicit": {"type": "boolean"}, "rationale": STR}),
            system_prompt=POLICY + " Decide if the message asks to stop receiving messages. When unsure answer 'unclear'.",
            fallback=lambda i: classify_unsub(i.text),
            tools=["suppression.add"],
        ),
        AgentSpec(
            key="task_extractor",
            name="Task Extractor",
            responsibilities="Extracts action items and due dates from meeting notes or briefs.",
            permission="campaigns:read",
            input_model=TextInput,
            output_schema=_schema({"tasks": {"type": "array", "items": _schema({"title": STR, "due_date": STR})}}),
            system_prompt=POLICY + " Extract explicit action items only. due_date is YYYY-MM-DD or empty.",
            fallback=lambda i: extract_tasks(i.text),
            tools=["asana.create_task"],
            requires_approval=True,
        ),
        AgentSpec(
            key="summarizer",
            name="Document Summarizer",
            responsibilities="Summarizes documents and reports for internal staff.",
            permission="ai:read",
            input_model=TextInput,
            output_schema=_schema({"summary": STR, "key_points": STRS}),
            system_prompt=POLICY + " Summarize faithfully without adding claims.",
            fallback=lambda i: summarize(i.text),
        ),
        AgentSpec(
            key="data_classifier",
            name="Data Classifier",
            responsibilities="Sorts operational items (files, requests, tickets) into staff-defined categories.",
            permission="ai:read",
            input_model=ClassifyInput,
            output_schema=_schema({"results": {"type": "array", "items": _schema({"item": STR, "category": STR, "needs_review": {"type": "boolean"}})}}),
            system_prompt=POLICY + " Use only the provided categories; mark needs_review when uncertain.",
            fallback=classify_items,
        ),
    ]
}


async def run_agent(
    key: str, raw_input: dict[str, Any], *, organization_id: str, client_id: str | None, user_id: str
) -> AgentExecution:
    spec = AGENTS.get(key)
    if spec is None:
        raise ValidationFailed(f"Unknown agent {key}")
    try:
        inp = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        raise ValidationFailed("Invalid agent input", details=[e["msg"] for e in exc.errors()]) from exc

    provider = get_provider()
    execution = AgentExecution(
        organization_id=organization_id, client_id=client_id, agent=key, user_id=user_id,
        input=json.loads(inp.model_dump_json()), provider=provider.name, model=provider.model,
    )
    started = time.perf_counter()
    try:
        if spec.use_llm:
            comp = await provider.structured(
                system=spec.system_prompt, user=inp.model_dump_json(), schema_name=key,
                schema=spec.output_schema, fallback=lambda: spec.fallback(inp),
            )
        else:
            from app.services.ai.providers import Completion

            comp = Completion(output=spec.fallback(inp), provider="deterministic", model="planner-v1")
        output = comp.output
        if key == "unsubscribe_classifier":
            # Safety invariant: explicit opt-out language can never be downgraded by a model.
            rule = classify_unsub(inp.text)  # type: ignore[attr-defined]
            if rule["explicit"]:
                output = rule
        execution.output = output
        execution.provider, execution.model = comp.provider, comp.model
        execution.prompt_tokens, execution.completion_tokens = comp.prompt_tokens, comp.completion_tokens
        execution.status = "awaiting_approval" if spec.requires_approval else "succeeded"
    except ValidationFailed:
        raise
    except Exception as exc:  # provider/network failures are recorded, not swallowed silently
        execution.status, execution.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
    execution.duration_ms = int((time.perf_counter() - started) * 1000)
    async with session_scope() as s:
        s.add(execution)
        await s.flush()
        audit(s, action=f"agent.run.{execution.status}", target_type="agent_execution", target_id=execution.id,
              organization_id=organization_id, client_id=client_id, actor_user_id=user_id, details={"agent": key})
    return execution
