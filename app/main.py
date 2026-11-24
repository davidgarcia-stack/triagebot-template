from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import classifier, db
from app.models import (
    ALLOWED_CATEGORIES,
    ALLOWED_PRIORITIES,
    REOPENABLE_STATUSES,
    STATUS_LABELS,
    Category,
    Priority,
    Status,
    Ticket,
    TicketCreate,
    TicketUpdate,
    is_valid_transition,
    next_statuses,
)

load_dotenv()

app = FastAPI(title="TriageBot")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def since(iso_timestamp: str, now: datetime | None = None) -> str:
    """Tiempo transcurrido en texto relativo: "hace 5 min", "hace 3 h", "hace 2 días"."""
    then = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    seconds = max(0, int(((now or datetime.now(UTC)) - then).total_seconds()))
    if seconds < 60:
        return "hace un momento"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86400:
        return f"hace {seconds // 3600} h"
    days = seconds // 86400
    return f"hace {days} día" if days == 1 else f"hace {days} días"


templates.env.filters["since"] = since
templates.env.globals.update(
    status_labels=STATUS_LABELS,
    next_statuses=next_statuses,
    reopenable_statuses=REOPENABLE_STATUSES,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def board(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"tickets": db.list_tickets()})


def _fallback() -> dict:
    return {**classifier.FALLBACK_CLASSIFICATION, "tags": []}


def _classify(title: str, description: str) -> dict:
    """Clasifica el ticket; ante cualquier fallo o salida inválida devuelve el fallback."""
    try:
        result = classifier.classify_ticket(title, description)
    except Exception:
        return _fallback()

    if (
        not isinstance(result, dict)
        or result.get("category") not in ALLOWED_CATEGORIES
        or result.get("priority") not in ALLOWED_PRIORITIES
        or not isinstance(result.get("tags"), list)
        or not all(isinstance(tag, str) for tag in result["tags"])
    ):
        return _fallback()

    return {
        "category": result["category"],
        "priority": result["priority"],
        "tags": list(result["tags"]),
    }


@app.post("/tickets", status_code=201, response_model=Ticket)
def create_ticket(request: Request, payload: TicketCreate):
    classification = _classify(payload.title, payload.description)
    ticket = db.create_ticket(payload.title, payload.description, classification)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request, "_rows.html", {"tickets": db.list_tickets()}, status_code=201
        )
    return ticket


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: Category | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
) -> list[dict]:
    return db.list_tickets(category=category, priority=priority, status=status)


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(request: Request, ticket_id: int, payload: TicketUpdate):
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if payload.status is not None and not is_valid_transition(ticket["status"], payload.status):
        raise HTTPException(
            status_code=422,
            detail=f"Transición no permitida: {ticket['status']} → {payload.status}",
        )
    updated = db.update_ticket(ticket_id, status=payload.status, priority=payload.priority)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "_row.html", {"ticket": updated})
    return updated
