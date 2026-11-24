from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import classifier, db
from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES, Ticket, TicketCreate

app = FastAPI(title="TriageBot")
templates = Jinja2Templates(directory="templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"tickets": db.list_tickets()})


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
