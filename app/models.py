from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}

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
