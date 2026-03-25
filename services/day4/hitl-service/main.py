"""
HITL Service — DPDP Compliance OS  Day 4
Human-in-the-Loop review queue for DPO/Legal decisions on:
  - Sensitive rights requests (erasure, portability for >10k records)
  - Breach notifications (harm score > threshold)
  - DPIA approvals
  - Cross-border transfers flagged by PEP
  - AI model deployment after bias alerts
"""

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Gauge, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="HITL Service", version="1.0.0",
              description="Human-in-the-Loop review queue for compliance decisions requiring human judgment")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

TASKS_CREATED   = Counter("hitl_tasks_created_total", "HITL tasks created", ["task_type"])
TASKS_RESOLVED  = Counter("hitl_tasks_resolved_total", "HITL tasks resolved", ["decision"])
QUEUE_DEPTH     = Gauge("hitl_queue_depth", "Current HITL queue depth", ["priority"])


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class TaskType(str, Enum):
    RIGHTS_REQUEST_REVIEW  = "rights_request_review"
    DPIA_APPROVAL          = "dpia_approval"
    BREACH_NOTIFICATION    = "breach_notification"
    CROSS_BORDER_APPROVAL  = "cross_border_approval"
    AI_MODEL_DEPLOYMENT    = "ai_model_deployment"
    PENALTY_APPEAL         = "penalty_appeal"
    ERASURE_LARGE_SCALE    = "erasure_large_scale"
    CHILD_DATA_EXCEPTION   = "child_data_exception"


class Priority(str, Enum):
    CRITICAL = "critical"   # 4-hour SLA
    HIGH     = "high"       # 24-hour SLA
    MEDIUM   = "medium"     # 72-hour SLA
    LOW      = "low"        # 7-day SLA


class TaskStatus(str, Enum):
    PENDING    = "pending"
    ASSIGNED   = "assigned"
    IN_REVIEW  = "in_review"
    APPROVED   = "approved"
    REJECTED   = "rejected"
    DEFERRED   = "deferred"
    ESCALATED  = "escalated"
    EXPIRED    = "expired"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT  = "reject"
    DEFER   = "defer"
    ESCALATE = "escalate"


SLA_HOURS: dict[Priority, int] = {
    Priority.CRITICAL: 4,
    Priority.HIGH:     24,
    Priority.MEDIUM:   72,
    Priority.LOW:      168,
}


class HITLTaskRequest(BaseModel):
    task_type: TaskType
    reference_id: str
    reference_type: str
    priority: Priority = Priority.MEDIUM
    title: str
    description: str
    context: dict = {}
    requestor_id: str
    requestor_role: str
    preferred_reviewer_roles: list[str] = ["dpo"]
    auto_escalate_after_hours: Optional[int] = None


class HITLTask(BaseModel):
    task_id: str
    task_type: TaskType
    reference_id: str
    priority: Priority
    status: TaskStatus
    title: str
    description: str
    context: dict
    requestor_id: str
    assigned_to: Optional[str]
    created_at: str
    due_at: str
    sla_hours: int
    workflow_id: Optional[str]


class ReviewRequest(BaseModel):
    reviewer_id: str
    reviewer_role: str
    decision: ReviewDecision
    rationale: str
    conditions: list[str] = []


# ---------------------------------------------------------------------------
# In-memory task store (replace with DB in production)
# ---------------------------------------------------------------------------
_tasks: dict[str, dict] = {}
_queue: list[str] = []   # Ordered by priority + created_at


# ---------------------------------------------------------------------------
# Service logic
# ---------------------------------------------------------------------------
def create_task(req: HITLTaskRequest) -> HITLTask:
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    sla = SLA_HOURS[req.priority]
    due_at = now + timedelta(hours=sla)

    # Auto-assign escalation window (default: half the SLA)
    auto_escalate = req.auto_escalate_after_hours or (sla // 2)

    task = {
        "task_id": task_id,
        "task_type": req.task_type.value,
        "reference_id": req.reference_id,
        "reference_type": req.reference_type,
        "priority": req.priority.value,
        "status": TaskStatus.PENDING.value,
        "title": req.title,
        "description": req.description,
        "context": req.context,
        "requestor_id": req.requestor_id,
        "preferred_reviewer_roles": req.preferred_reviewer_roles,
        "assigned_to": None,
        "created_at": now.isoformat(),
        "due_at": due_at.isoformat(),
        "sla_hours": sla,
        "auto_escalate_after_hours": auto_escalate,
        "workflow_id": f"hitl-{task_id}",
        "timeline": [{"event": "CREATED", "ts": now.isoformat(), "actor": req.requestor_id}],
    }

    _tasks[task_id] = task
    _queue.append(task_id)

    TASKS_CREATED.labels(task_type=req.task_type.value).inc()
    QUEUE_DEPTH.labels(priority=req.priority.value).inc()

    log.info("hitl.task.created", task_id=task_id, type=req.task_type.value, priority=req.priority.value, due=due_at.isoformat())
    return HITLTask(**{k: v for k, v in task.items() if k != "timeline"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "hitl-service", "queue_depth": len(_queue)}


@app.post("/hitl/tasks", response_model=HITLTask, status_code=201)
async def create_hitl_task(req: HITLTaskRequest):
    """Create a new HITL review task."""
    return create_task(req)


@app.get("/hitl/tasks/{task_id}", response_model=HITLTask)
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return HITLTask(**{k: v for k, v in task.items() if k != "timeline"})


@app.get("/hitl/queue")
async def get_queue(priority: Optional[Priority] = None, status: Optional[TaskStatus] = None, limit: int = 50):
    """Return prioritised review queue for DPO/Legal dashboards."""
    tasks = list(_tasks.values())

    if priority:
        tasks = [t for t in tasks if t["priority"] == priority.value]
    if status:
        tasks = [t for t in tasks if t["status"] == status.value]

    priority_order = {p.value: i for i, p in enumerate(Priority)}
    tasks.sort(key=lambda t: (priority_order.get(t["priority"], 99), t["created_at"]))

    return {
        "tasks": tasks[:limit],
        "total": len(tasks),
        "by_priority": {
            p.value: sum(1 for t in _tasks.values() if t["priority"] == p.value and t["status"] == TaskStatus.PENDING.value)
            for p in Priority
        },
    }


@app.post("/hitl/tasks/{task_id}/assign")
async def assign_task(task_id: str, reviewer_id: str, reviewer_role: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] != TaskStatus.PENDING.value:
        raise HTTPException(409, f"Task is in status: {task['status']}, cannot assign")

    task["status"] = TaskStatus.ASSIGNED.value
    task["assigned_to"] = reviewer_id
    task["timeline"].append({"event": "ASSIGNED", "ts": datetime.now(timezone.utc).isoformat(), "actor": reviewer_id, "role": reviewer_role})

    log.info("hitl.task.assigned", task_id=task_id, reviewer=reviewer_id)
    return {"task_id": task_id, "status": "assigned", "reviewer": reviewer_id}


@app.post("/hitl/tasks/{task_id}/review")
async def submit_review(task_id: str, review: ReviewRequest):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] not in (TaskStatus.ASSIGNED.value, TaskStatus.IN_REVIEW.value):
        raise HTTPException(409, "Task must be assigned before review")

    now = datetime.now(timezone.utc)
    decision_map = {
        ReviewDecision.APPROVE:   TaskStatus.APPROVED,
        ReviewDecision.REJECT:    TaskStatus.REJECTED,
        ReviewDecision.DEFER:     TaskStatus.DEFERRED,
        ReviewDecision.ESCALATE:  TaskStatus.ESCALATED,
    }

    new_status = decision_map[review.decision]
    task["status"] = new_status.value
    task["timeline"].append({
        "event": f"REVIEW_{review.decision.value.upper()}",
        "ts": now.isoformat(),
        "actor": review.reviewer_id,
        "role": review.reviewer_role,
        "rationale": review.rationale,
        "conditions": review.conditions,
    })

    TASKS_RESOLVED.labels(decision=review.decision.value).inc()
    QUEUE_DEPTH.labels(priority=task["priority"]).dec()
    _queue.remove(task_id) if task_id in _queue else None

    log.info("hitl.task.reviewed", task_id=task_id, decision=review.decision.value, reviewer=review.reviewer_id)
    return {
        "task_id": task_id,
        "status": new_status.value,
        "decision": review.decision.value,
        "rationale": review.rationale,
        "conditions": review.conditions,
        "reviewed_at": now.isoformat(),
    }


@app.get("/hitl/tasks/{task_id}/timeline")
async def get_timeline(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task_id": task_id, "timeline": task["timeline"]}


@app.post("/hitl/tasks/{task_id}/escalate")
async def escalate_task(task_id: str, reason: str, escalated_by: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    task["status"] = TaskStatus.ESCALATED.value
    task["priority"] = Priority.CRITICAL.value
    task["timeline"].append({"event": "ESCALATED", "ts": datetime.now(timezone.utc).isoformat(), "actor": escalated_by, "reason": reason})
    log.warning("hitl.task.escalated", task_id=task_id, reason=reason)
    return {"task_id": task_id, "status": "escalated", "escalated_to": "board_level"}
