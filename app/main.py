from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import classifier, db
from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES, Ticket, TicketCreate

app = FastAPI(title="TriageBot")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


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

    # HTMX (el formulario de /) pide HTML: devolvemos las filas ya renderizadas para que
    # hx-swap las meta en el <tbody>. Cualquier otro cliente recibe el JSON del SPEC §4.
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "_tickets_rows.html",
            {"tickets": db.list_tickets()},
            status_code=201,
            headers={"Vary": "HX-Request"},
        )
    return ticket


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
