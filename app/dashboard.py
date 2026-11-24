"""Métricas y geometría de gráficas del tablero.

Módulo puro: recibe la lista de tickets (tal como la devuelve `db.list_tickets()`, ya con
`due_at`) y la hora actual en ISO UTC. No importa FastAPI, no hace SQL y no llama al LLM.
Las plantillas solo pintan lo que devuelve este módulo.
"""

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import ISO_FORMAT

# Estados que cuentan como «hecho»: ni están abiertos ni pueden vencer (SPEC §4).
DONE_STATUSES = {"resolved", "closed"}

MADRID = ZoneInfo("Europe/Madrid")
SPARK_DAYS = 14
TREND_RANGES = (7, 30, 90)

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
SHORT_MONTHS = [m[:3] for m in MONTHS]

CATEGORY_LABELS = {
    "bug": "Bug",
    "feature_request": "Petición",
    "question": "Pregunta",
    "urgent": "Urgente",
}

Predicate = Callable[[dict], bool]


def _parse(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=UTC)


def _pct(part: int, total: int) -> int:
    return round(100 * part / total) if total else 0


def is_open(ticket: dict) -> bool:
    return ticket["status"] not in DONE_STATUSES


def is_overdue(ticket: dict, now: str) -> bool:
    """Vencido = fecha límite pasada y ni resuelto ni cerrado (SPEC §4). ISO UTC compara bien."""
    return is_open(ticket) and ticket["due_at"] < now


def daily_counts(
    tickets: list[dict],
    today: date,
    days: int,
    predicate: Predicate = lambda t: True,
    field: str = "created_at",
) -> list[tuple[date, int]]:
    """Cuántos tickets caen en cada uno de los últimos `days` días (hoy incluido), por `field`."""
    start = today - timedelta(days=days - 1)
    counts = {start + timedelta(days=i): 0 for i in range(days)}
    for ticket in tickets:
        if predicate(ticket):
            day = _parse(ticket[field]).date()
            if day in counts:
                counts[day] += 1
    return list(counts.items())


def week_change(tickets: list[dict], today: date, predicate: Predicate) -> dict | None:
    """Creados en los últimos 7 días frente a los 7 anteriores.

    None si no hay base de comparación (la semana anterior no tiene tickets).
    """
    counts = [n for _, n in daily_counts(tickets, today, 14, predicate)]
    previous, last = sum(counts[:7]), sum(counts[7:])
    if previous == 0:
        return None
    change = round(100 * (last - previous) / previous)
    return {"pct": abs(change), "up": change >= 0}


def sparkline(values: list[int], width: int = 240, height: int = 56, pad: int = 4) -> dict:
    """Paths SVG (línea y área) de una mini-gráfica dentro de un viewBox width×height."""
    top = max(values) if values and max(values) > 0 else 1
    step = (width - 2 * pad) / max(len(values) - 1, 1)
    usable = height - 2 * pad
    points = [(pad + i * step, height - pad - (v / top) * usable) for i, v in enumerate(values)]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{line} L{points[-1][0]:.1f},{height} L{points[0][0]:.1f},{height} Z"
    return {"line": line, "area": area, "width": width, "height": height}


def _nice_max(value: int, intervals: int = 4) -> int:
    """Máximo «redondo» del eje Y, múltiplo de un paso 1-2-5 × 10^k."""
    if value <= intervals:
        return intervals
    raw = value / intervals
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw)
    return int(step * intervals)


def short_date(day: date) -> str:
    return f"{day.day} {SHORT_MONTHS[day.month - 1]}"


def trend_chart(
    tickets: list[dict], now: str, days: int, width: int = 1000, height: int = 300
) -> dict:
    """Geometría de la gráfica «Tickets creados» para los últimos `days` días.

    El tablero pide dos tamaños: uno ancho para escritorio y otro compacto para móvil, para que
    el texto del SVG no se agrande ni se encoja al escalar.
    """
    left, right, top, bottom = 36, 12, 12, 30
    plot_w, plot_h = width - left - right, height - top - bottom

    series = daily_counts(tickets, _parse(now).date(), days)
    y_max = _nice_max(max(n for _, n in series))
    step = plot_w / (len(series) - 1)

    points = []
    for i, (day, count) in enumerate(series):
        x = left + i * step
        y = top + plot_h - count / y_max * plot_h
        points.append(
            {"x": round(x, 1), "y": round(y, 1), "value": count, "label": short_date(day)}
        )

    line = "M" + " L".join(f"{p['x']},{p['y']}" for p in points)
    baseline = top + plot_h
    area = f"{line} L{points[-1]['x']},{baseline} L{points[0]['x']},{baseline} Z"

    y_ticks = [
        {"value": y_max * k // 4, "y": round(top + plot_h - plot_h * k / 4, 1)} for k in range(5)
    ]
    # Una etiqueta cada ~90 px como mucho, para que no se pisen en la versión compacta.
    max_labels = max(width // 90, 2)
    every = max({7: 1, 30: 5, 90: 15}.get(days, 1), math.ceil(days / max_labels))
    x_ticks = [
        {**p, "anchor": "end" if i == len(points) - 1 else "middle"}
        for i, p in enumerate(points)
        if (len(points) - 1 - i) % every == 0
    ]
    # La primera etiqueta no puede salirse por la izquierda.
    if x_ticks and x_ticks[0]["x"] - left < 24:
        x_ticks[0]["anchor"] = "start"

    return {
        "days": days,
        "ranges": TREND_RANGES,
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "top": top,
        "baseline": baseline,
        "hit_width": round(step, 1),
        "line": line,
        "area": area,
        "points": points,
        "y_ticks": y_ticks,
        "x_ticks": x_ticks,
        "total": sum(p["value"] for p in points),
    }


def category_breakdown(tickets: list[dict]) -> dict:
    """Reparto por categoría (orden fijo del SPEC), con % del total y ancho relativo de barra."""
    total = len(tickets)
    counts = {key: 0 for key in CATEGORY_LABELS}
    for ticket in tickets:
        if ticket["category"] in counts:
            counts[ticket["category"]] += 1
    top = max(counts.values()) or 1
    rows = [
        {
            "key": key,
            "label": CATEGORY_LABELS[key],
            "count": count,
            "pct": _pct(count, total),
            "bar": round(100 * count / top),
        }
        for key, count in counts.items()
    ]
    return {"total": total, "rows": rows}


def greeting(local: datetime) -> str:
    if 6 <= local.hour < 13:
        return "Buenos días"
    if 13 <= local.hour < 21:
        return "Buenas tardes"
    return "Buenas noches"


def long_date(local: datetime) -> str:
    return (
        f"{WEEKDAYS[local.weekday()]}, {local.day} de {MONTHS[local.month - 1]} de {local.year}"
    )


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def headline(open_count: int, overdue: int, p1_open: int) -> str:
    if open_count == 0:
        return "No hay tickets pendientes. Todo está al día."
    parts = []
    if overdue:
        parts.append(_plural(overdue, "ticket vencido", "tickets vencidos"))
    if p1_open:
        parts.append(_plural(p1_open, "P1 sin cerrar", "P1 sin cerrar"))
    if not parts:
        return "Todo en plazo: ningún ticket abierto ha superado su fecha límite."
    return "Hay " + " y ".join(parts) + "."


def build_summary(tickets: list[dict], now: str) -> dict:
    """Banner y tarjetas KPI del tablero."""
    today = _parse(now).date()
    local = _parse(now).astimezone(MADRID)

    open_tickets = [t for t in tickets if is_open(t)]
    total, open_count = len(tickets), len(open_tickets)
    in_progress = sum(t["status"] == "in_progress" for t in tickets)
    done = total - open_count
    overdue = sum(is_overdue(t, now) for t in tickets)

    def is_p1(t: dict) -> bool:
        return t["priority"] == "P1"

    def is_urgent(t: dict) -> bool:
        return t["category"] == "urgent"

    p1_open = sum(is_p1(t) for t in open_tickets)
    urgent_open = sum(is_urgent(t) for t in open_tickets)

    def spark(predicate: Predicate = lambda t: True, field: str = "created_at") -> dict:
        values = [n for _, n in daily_counts(tickets, today, SPARK_DAYS, predicate, field)]
        return sparkline(values)

    kpis = [
        {
            "key": "open",
            "label": "Tickets abiertos",
            "value": open_count,
            "tone": "indigo",
            "icon": "inbox",
            "change": week_change(tickets, today, lambda t: True),
            "caption": "creados vs semana anterior",
            "spark": spark(),
        },
        {
            "key": "p1",
            "label": "P1 sin cerrar",
            "value": p1_open,
            "tone": "rose",
            "icon": "flame",
            "change": week_change(tickets, today, is_p1),
            "caption": "P1 creados vs semana anterior",
            "spark": spark(is_p1),
        },
        {
            "key": "urgent",
            "label": "Urgentes abiertos",
            "value": urgent_open,
            "tone": "cyan",
            "icon": "bolt",
            "change": week_change(tickets, today, is_urgent),
            "caption": "urgentes creados vs semana anterior",
            "spark": spark(is_urgent),
        },
        {
            "key": "overdue",
            "label": "Fuera de plazo",
            "value": overdue,
            "tone": "amber",
            "icon": "clock",
            "change": None,
            "caption": f"de {_plural(open_count, 'ticket abierto', 'tickets abiertos')}",
            "spark": spark(is_open, field="due_at"),
        },
    ]

    return {
        "date": long_date(local),
        "greeting": greeting(local),
        "headline": headline(open_count, overdue, p1_open),
        "total": total,
        "open": open_count,
        "progress": [
            {"label": "Resueltos", "value": done, "of": total, "pct": _pct(done, total)},
            {
                "label": "En curso",
                "value": in_progress,
                "of": total,
                "pct": _pct(in_progress, total),
            },
            {
                "label": "En plazo",
                "value": open_count - overdue,
                "of": open_count,
                "pct": _pct(open_count - overdue, open_count),
            },
        ],
        "kpis": kpis,
    }
