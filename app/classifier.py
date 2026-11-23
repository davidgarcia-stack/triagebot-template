import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES

logger = logging.getLogger(__name__)

FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 2  # una llamada + como mucho un reintento (SPEC §5)
MAX_TAGS = 5
MAX_TAG_LENGTH = 30

SYSTEM_PROMPT = """\
Eres un asistente de triage de tickets de soporte. Clasifica el ticket del usuario.

Responde SOLO con un objeto JSON, sin texto adicional ni markdown, con esta forma exacta:
{"category": "...", "priority": "...", "tags": ["..."]}

category (exactamente uno, en minúsculas):
- "bug": algo que debería funcionar y falla.
- "feature_request": petición de una funcionalidad nueva o una mejora.
- "question": duda o consulta sobre cómo hacer algo o sobre una política.
- "urgent": caída o impacto crítico e inmediato que requiere atención ya.

priority (exactamente uno):
- "P1": bloquea a varios usuarios o al negocio; hay que atenderlo de inmediato.
- "P2": afecta a trabajo normal pero hay alternativa o no es inmediato.
- "P3": baja urgencia, mejora o consulta.

tags: entre 0 y 5 etiquetas cortas, en minúsculas, con guiones en vez de espacios.
"""


def _fallback() -> dict:
    return {**FALLBACK_CLASSIFICATION, "tags": []}


def _get_client() -> OpenAI | None:
    """Cliente de OpenRouter, o None si no hay API key. La key solo viene del entorno."""
    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    # max_retries=0: el único reintento lo controlamos nosotros, no el SDK.
    return OpenAI(
        base_url=OPENROUTER_BASE_URL, api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0
    )


def _call_llm(client: OpenAI, title: str, description: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Título: {title}\n\nDescripción: {description}"},
        ],
    )
    return response.choices[0].message.content or ""


def _parse(raw: str) -> dict | None:
    """Extrae un objeto JSON de la respuesta, tolerando fences de markdown y texto alrededor."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _clean_tags(tags: list) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip().lower()
        if tag and len(tag) <= MAX_TAG_LENGTH and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:MAX_TAGS]


def _validate(data: dict) -> dict | None:
    """Devuelve la clasificación válida o None. Category/priority se comparan sin normalizar."""
    category, priority, tags = data.get("category"), data.get("priority"), data.get("tags")
    if category not in ALLOWED_CATEGORIES or priority not in ALLOWED_PRIORITIES:
        return None
    if not isinstance(tags, list):
        return None
    return {"category": category, "priority": priority, "tags": _clean_tags(tags)}


def classify_ticket(title: str, description: str) -> dict:
    """Clasifica un ticket con gpt-oss-120b vía OpenRouter.

    Nunca propaga excepciones: ante cualquier problema (sin API key, error del SDK, respuesta
    que no es JSON, valores fuera de los enums) devuelve FALLBACK_CLASSIFICATION.
    """
    try:
        client = _get_client()
        if client is None:
            return _fallback()

        raw = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = _call_llm(client, title, description)
                break
            except Exception as exc:  # solo se reintenta si la llamada falla
                # No se loguea el contenido del ticket, solo el tipo de error.
                logger.warning("LLM call failed (attempt %d): %s", attempt, type(exc).__name__)
        if raw is None:
            return _fallback()

        data = _parse(raw)
        result = _validate(data) if data is not None else None
        return result if result is not None else _fallback()
    except Exception as exc:
        logger.warning("Classifier error: %s", type(exc).__name__)
        return _fallback()
