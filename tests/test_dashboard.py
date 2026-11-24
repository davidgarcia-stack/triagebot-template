"""Tablero rediseñado: métricas (app/dashboard.py), fragmentos HTMX y página (SPEC §7)."""

from datetime import UTC, datetime, timedelta

import pytest

from app import dashboard, db
from app.models import ISO_FORMAT, compute_due_at

NOW = "2026-11-24T12:00:00Z"


def make(
    created_days_ago: float = 0,
    category: str = "bug",
    priority: str = "P3",
    status: str = "open",
    now: str = NOW,
) -> dict:
    created = datetime.strptime(now, ISO_FORMAT) - timedelta(days=created_days_ago)
    created_at = created.strftime(ISO_FORMAT)
    return {
        "category": category,
        "priority": priority,
        "status": status,
        "created_at": created_at,
        "due_at": compute_due_at(created_at, priority),
    }


def kpi(summary: dict, key: str) -> dict:
    return next(k for k in summary["kpis"] if k["key"] == key)


# --- build_summary -----------------------------------------------------------------


def test_empty_board_has_zeros_and_no_division_by_zero():
    summary = dashboard.build_summary([], NOW)

    assert summary["total"] == summary["open"] == 0
    assert [p["pct"] for p in summary["progress"]] == [0, 0, 0]
    assert [k["value"] for k in summary["kpis"]] == [0, 0, 0, 0]
    assert summary["headline"].startswith("No hay tickets pendientes")


def test_counts_by_status_priority_category_and_overdue():
    tickets = [
        make(0, "urgent", "P1"),
        make(3, "bug", "P1"),  # P1 de hace 3 días → vencido
        make(3, "bug", "P1", status="closed"),  # cerrado: nunca vencido
        make(1, "question", "P3", status="in_progress"),
    ]

    summary = dashboard.build_summary(tickets, NOW)

    assert summary["total"] == 4
    assert summary["open"] == 3
    assert kpi(summary, "open")["value"] == 3
    assert kpi(summary, "p1")["value"] == 2
    assert kpi(summary, "urgent")["value"] == 1
    assert kpi(summary, "overdue")["value"] == 1
    resolved, in_progress, on_time = summary["progress"]
    assert (resolved["value"], resolved["of"], resolved["pct"]) == (1, 4, 25)
    assert (in_progress["value"], in_progress["pct"]) == (1, 25)
    assert (on_time["value"], on_time["of"], on_time["pct"]) == (2, 3, 67)
    assert summary["headline"] == "Hay 1 ticket vencido y 2 P1 sin cerrar."


def test_headline_when_everything_is_on_time():
    summary = dashboard.build_summary([make(0, priority="P3")], NOW)
    assert summary["headline"].startswith("Todo en plazo")


def test_week_change_compares_last_7_days_with_previous_7():
    tickets = [make(1), make(2), make(3), make(9)]  # 3 esta semana, 1 la anterior

    change = dashboard.week_change(tickets, datetime.strptime(NOW, ISO_FORMAT).date(), bool)

    assert change == {"pct": 200, "up": True}


def test_week_change_without_previous_week_is_none():
    today = datetime.strptime(NOW, ISO_FORMAT).date()
    assert dashboard.week_change([make(1)], today, bool) is None


def test_daily_counts_covers_every_day_including_today():
    today = datetime.strptime(NOW, ISO_FORMAT).date()
    series = dashboard.daily_counts([make(0), make(0), make(2), make(40)], today, 14)

    assert len(series) == 14
    assert series[-1] == (today, 2)
    assert series[-3][1] == 1
    assert sum(n for _, n in series) == 3  # el de hace 40 días queda fuera


def test_greeting_and_spanish_date_use_madrid_time():
    summary = dashboard.build_summary([], "2026-11-24T12:30:00Z")  # 13:30 en Madrid
    assert summary["greeting"] == "Buenas tardes"
    assert summary["date"] == "martes, 24 de noviembre de 2026"
    assert dashboard.build_summary([], "2026-11-24T06:00:00Z")["greeting"] == "Buenos días"
    assert dashboard.build_summary([], "2026-11-24T22:00:00Z")["greeting"] == "Buenas noches"


# --- Geometría de gráficas -----------------------------------------------------------


@pytest.mark.parametrize("days", [7, 30, 90])
def test_trend_points_stay_inside_the_plot(days):
    tickets = [make(i % days, priority="P2") for i in range(50)]

    chart = dashboard.trend_chart(tickets, NOW, days)

    assert len(chart["points"]) == days
    assert chart["total"] == 50
    for p in chart["points"]:
        assert chart["left"] <= p["x"] <= chart["right"]
        assert chart["top"] <= p["y"] <= chart["baseline"]
    assert chart["y_ticks"][0]["value"] == 0
    assert chart["y_ticks"][-1]["value"] >= max(p["value"] for p in chart["points"])
    last = chart["x_ticks"][-1]
    assert (last["x"], last["label"]) == (chart["points"][-1]["x"], chart["points"][-1]["label"])
    assert last["anchor"] == "end"  # hoy siempre se etiqueta, sin salirse por la derecha


@pytest.mark.parametrize("days", [7, 30, 90])
def test_compact_trend_labels_do_not_overlap(days):
    chart = dashboard.trend_chart([], NOW, days, width=480, height=280)
    xs = [t["x"] for t in chart["x_ticks"]]
    # «24 nov» mide ~40 px a 12 px: con 60 px de separación no se pisan.
    assert all(b - a >= 60 for a, b in zip(xs, xs[1:], strict=False))


def test_trend_with_no_tickets_is_a_flat_line_on_the_baseline():
    chart = dashboard.trend_chart([], NOW, 7)
    assert {p["y"] for p in chart["points"]} == {chart["baseline"]}


def test_sparkline_stays_inside_viewbox():
    spark = dashboard.sparkline([0, 3, 1, 7, 0])
    coords = [float(v) for pair in spark["line"][1:].split(" L") for v in pair.split(",")]
    xs, ys = coords[0::2], coords[1::2]
    assert all(0 <= x <= spark["width"] for x in xs)
    assert all(0 <= y <= spark["height"] for y in ys)


def test_category_breakdown_keeps_spec_order_and_percentages():
    tickets = [make(category="bug"), make(category="bug"), make(category="urgent"), make()]

    breakdown = dashboard.category_breakdown(tickets)

    assert [r["key"] for r in breakdown["rows"]] == ["bug", "feature_request", "question", "urgent"]
    bug = breakdown["rows"][0]
    assert (bug["count"], bug["pct"], bug["bar"]) == (3, 75, 100)
    assert breakdown["rows"][1]["bar"] == 0


# --- Endpoints y página --------------------------------------------------------------


def test_board_page_has_banner_kpis_and_charts(create_ticket, client):
    create_ticket(category="urgent", priority="P1")
    html = client.get("/").text

    for text in ("Tablero de triage", "Tickets abiertos", "P1 sin cerrar", "Urgentes abiertos",
                 "Fuera de plazo", "Tickets creados", "Por categoría", "Nuevo ticket"):
        assert text in html
    assert 'id="summary"' in html and 'id="trend"' in html and 'id="categories"' in html


def test_ai_status_pill_reflects_api_key(client, monkeypatch):
    monkeypatch.setattr("app.classifier.load_dotenv", lambda: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert "IA en modo fallback" in client.get("/").text

    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-de-prueba")
    html = client.get("/").text
    assert "IA conectada" in html
    assert "clave-de-prueba" not in html


def test_summary_partial_returns_summary_and_oob_categories(create_ticket, client):
    create_ticket()
    response = client.get("/partials/resumen")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="summary"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "<html" not in response.text


@pytest.mark.parametrize("days", [7, 30, 90])
def test_trend_partial_accepts_supported_ranges(client, days):
    response = client.get("/partials/tendencia", params={"dias": days})

    assert response.status_code == 200
    assert f"Últimos {days} días" in response.text
    assert f'hx-get="/partials/tendencia?dias={days}"' in response.text  # recarga con su rango


@pytest.mark.parametrize("days", [12, 0, "abc"])
def test_trend_partial_rejects_other_ranges(client, days):
    assert client.get("/partials/tendencia", params={"dias": days}).status_code == 422


def test_htmx_post_triggers_dashboard_refresh(client, set_classification):
    response = client.post(
        "/tickets",
        json={"title": "Desde el formulario", "description": "descripción"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 201
    assert response.headers["HX-Trigger"] == "ticketsChanged"


def test_json_post_does_not_trigger_refresh(client, set_classification):
    response = client.post("/tickets", json={"title": "API", "description": "descripción"})

    assert response.headers["content-type"].startswith("application/json")
    assert "HX-Trigger" not in response.headers


def test_dashboard_reflects_tickets_in_the_database(create_ticket, client):
    ticket = create_ticket(priority="P1")
    conn = db.get_conn()
    with conn:
        old = (datetime.now(UTC) - timedelta(days=3)).strftime(ISO_FORMAT)
        conn.execute("UPDATE tickets SET created_at = ? WHERE id = ?", (old, ticket["id"]))
    conn.close()

    html = client.get("/partials/resumen").text

    assert "Hay 1 ticket vencido y 1 P1 sin cerrar." in html


def test_user_content_is_still_escaped(create_ticket, client):
    create_ticket(title="<script>alert(1)</script>")
    html = client.get("/").text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# --- Integración con el ciclo de vida (resolved) -------------------------------------


def test_resolved_counts_as_done_and_never_overdue():
    tickets = [
        make(3, priority="P1", status="resolved"),  # vencería, pero está resuelto
        make(3, priority="P1", status="closed"),
        make(0, priority="P3", status="open"),
    ]

    summary = dashboard.build_summary(tickets, NOW)

    assert summary["open"] == 1
    assert kpi(summary, "overdue")["value"] == 0
    assert kpi(summary, "p1")["value"] == 0
    resolved = summary["progress"][0]
    assert (resolved["value"], resolved["of"]) == (2, 3)


def test_htmx_patch_triggers_dashboard_refresh(create_ticket, client):
    ticket = create_ticket()

    response = client.patch(
        f"/tickets/{ticket['id']}", json={"status": "resolved"}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "ticketsChanged"
    assert f'id="ticket-{ticket["id"]}"' in response.text


def test_json_patch_does_not_trigger_refresh(create_ticket, client):
    ticket = create_ticket()

    response = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"})

    assert response.headers["content-type"].startswith("application/json")
    assert "HX-Trigger" not in response.headers
