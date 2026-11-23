"""Tests derived from SPEC.md sections 3 and 8 (module boundaries, non-negotiables)."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_classifier_does_not_import_fastapi():
    assert "fastapi" not in imported_modules(APP_DIR / "classifier.py")


def test_only_classifier_talks_to_the_llm_sdk():
    offenders = [
        path.name
        for path in APP_DIR.glob("*.py")
        if path.name != "classifier.py" and "openai" in imported_modules(path)
    ]

    assert offenders == []


def test_no_api_key_is_hardcoded_in_source():
    key_pattern = re.compile(r"sk-(or-)?[A-Za-z0-9_-]{16,}")
    offenders = [
        str(path.relative_to(ROOT))
        for path in [*APP_DIR.rglob("*.py"), *ROOT.glob("templates/*.html")]
        if key_pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_api_key_is_read_from_environment_variable():
    assert "OPENROUTER_API_KEY" in (APP_DIR / "classifier.py").read_text(encoding="utf-8")


def test_dotenv_is_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in [line.strip() for line in lines]


def test_expected_modules_and_templates_exist():
    for relative in (
        "app/main.py",
        "app/models.py",
        "app/db.py",
        "app/classifier.py",
        "templates/index.html",
        "templates/_tickets_table.html",
    ):
        assert (ROOT / relative).is_file(), f"missing {relative}"


def test_no_frontend_framework_is_used():
    templates = " ".join(
        path.read_text(encoding="utf-8").lower() for path in ROOT.glob("templates/*.html")
    )

    assert "react" not in templates
    assert "vue" not in templates
