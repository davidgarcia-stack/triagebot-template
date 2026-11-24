from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import classifier, dashboard, db
from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES, Ticket, TicketCreate

app = FastAPI(title="TriageBot")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DEFAULT_TREND_DAYS = 30


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _board_context(days: int = DEFAULT_TREND_DAYS) -> dict:
    """Todo lo que pintan el tablero y sus fragmentos HTMX, calculado de una sola lectura."""
    tickets = db.list_tickets()
    now = db.now_iso()
    return {
        "tickets": tickets,
        "now": now,
        "summary": dashboard.build_summary(tickets, now),
        "trend": dashboard.trend_chart(tickets, now, days),
        "trend_compact": dashboard.trend_chart(tickets, now, days, width=480, height=280),
        "categories": dashboard.category_breakdown(tickets),
        "ai_ready": classifier.is_configured(),
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def board(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", _board_context())


@app.get("/partials/resumen", response_class=HTMLResponse, include_in_schema=False)
def summary_partial(request: Request) -> HTMLResponse:
    """Banner + KPIs, y el reparto por categoría como swap out-of-band."""
    context = {**_board_context(), "oob": True}
    return templates.TemplateResponse(request, "_summary_refresh.html", context)


@app.get("/partials/tendencia", response_class=HTMLResponse, include_in_schema=False)
def trend_partial(request: Request, dias: int = DEFAULT_TREND_DAYS) -> HTMLResponse:
    if dias not in dashboard.TREND_RANGES:
        detail = f"dias debe ser uno de {dashboard.TREND_RANGES}"
        raise HTTPException(status_code=422, detail=detail)
    return templates.TemplateResponse(request, "_trend.html", _board_context(dias))


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
        # Filas para el <tbody>; el evento hace que resumen, KPIs y gráficas se recarguen.
        return templates.TemplateResponse(
            request,
            "_rows.html",
            {"tickets": db.list_tickets(), "now": db.now_iso()},
            status_code=201,
            headers={"HX-Trigger": "ticketCreated", "Vary": "HX-Request"},
        )
    return ticket


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
