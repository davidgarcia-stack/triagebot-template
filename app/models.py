from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Orden fijo de los enums (lo usan, p. ej., las claves de GET /tickets/stats).
CATEGORY_ORDER = ("bug", "feature_request", "question", "urgent")
PRIORITY_ORDER = ("P1", "P2", "P3")
ALLOWED_CATEGORIES = set(CATEGORY_ORDER)
ALLOWED_PRIORITIES = set(PRIORITY_ORDER)

# Ciclo de vida: se avanza en este orden (se pueden saltar pasos hacia delante).
STATUS_ORDER = ("open", "in_progress", "resolved", "closed")
ALLOWED_STATUSES = set(STATUS_ORDER)
REOPENABLE_STATUSES = {"resolved", "closed"}
STATUS_LABELS = {
    "open": "Abierto",
    "in_progress": "En curso",
    "resolved": "Resuelto",
    "closed": "Cerrado",
}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "resolved", "closed"]


def is_valid_transition(current: str, new: str) -> bool:
    """Mismo estado, cualquier avance, o reabrir (resolved/closed -> open)."""
    if current == new:
        return True
    if new == "open":
        return current in REOPENABLE_STATUSES
    return STATUS_ORDER.index(new) > STATUS_ORDER.index(current)


def next_statuses(current: str) -> list[str]:
    """Estados que se pueden elegir en el selector: el actual y los siguientes."""
    return list(STATUS_ORDER[STATUS_ORDER.index(current):])


# Plazo de resolución por prioridad, en horas naturales (SPEC §4, «Fecha límite»).
SLA_BY_PRIORITY = {
    "P1": timedelta(hours=24),
    "P2": timedelta(hours=72),
    "P3": timedelta(days=7),
}
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def compute_due_at(created_at: str, priority: str) -> str:
    """Fecha límite = created_at + plazo de la prioridad actual, en el mismo formato ISO UTC.

    Una prioridad desconocida usa el plazo más laxo (P3) para no romper la lectura del ticket.
    """
    sla = SLA_BY_PRIORITY.get(priority, SLA_BY_PRIORITY["P3"])
    return (datetime.strptime(created_at, ISO_FORMAT) + sla).strftime(ISO_FORMAT)


class TicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    priority: Priority | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "TicketUpdate":
        if self.status is None and self.priority is None:
            raise ValueError("Indica al menos status o priority")
        return self


class Ticket(BaseModel):
    id: int
    title: str
    description: str
    category: str
    priority: str
    tags: list[str]
    status: str
    created_at: datetime
    updated_at: datetime
    status_changed_at: datetime
    due_at: datetime


class TicketStats(BaseModel):
    """Conteos de GET /tickets/stats. Cada dict trae siempre todas las claves de su enum."""

    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
