from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "closed"}

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
    due_at: datetime
