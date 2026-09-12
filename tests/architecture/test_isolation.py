"""The product rules, enforced by reading source rather than by review.

Ported from v2 tests/architecture/test_llm_isolation.py and extended for v3's layout:
the drafting model sees one frozen ContextBundle and nothing else, only grounding builds
one, only knowledge resolves llm_diagnose, and each service touches only its own schema.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "services"
PY_SERVICES = sorted(p.parent.parent for p in SERVICES.glob("*/app/main.py"))

#: The Neon schema each service owns (business also owns org via SQLAlchemy metadata).
OWNED_SCHEMA = {
    "business": "org", "payments": "payments", "inquiry": "inquiry", "orchestrator": "cases",
    "grounding": "grounding", "response": "response", "control": "control", "knowledge": "knowledge", "gateway": "gw",
}


def sources(service: Path) -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in (service / "app").rglob("*.py")}


def imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_response_cannot_reach_raw_input_or_records():
    forbidden_imports = {"minio", "boto3", "faster_whisper", "onnxruntime", "sqlalchemy"}
    forbidden_urls = ("BUSINESS_URL", "INQUIRY_URL", "ASR_URL", "VISION_URL", "AUDIO_URL", "IMAGE_URL", "PAYMENTS_URL")
    for path, src in sources(SERVICES / "response").items():
        assert not imports(src) & forbidden_imports, f"{path} imports {imports(src) & forbidden_imports}"
        for name in forbidden_urls:
            assert name not in src, f"{path} references {name}; the drafting path reads only the bundle"


def test_generate_from_bundle_takes_exactly_the_bundle():
    tree = ast.parse((SERVICES / "response" / "app" / "main.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "generate_from_bundle")
    args = fn.args.args + fn.args.kwonlyargs
    assert [a.arg for a in args] == ["bundle"] and not fn.args.vararg and not fn.args.kwarg
    assert ast.unparse(args[0].annotation) == "ContextBundle"


def test_only_grounding_assemble_constructs_a_bundle():
    builders = []
    for svc in PY_SERVICES:
        for path, src in sources(svc).items():
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ContextBundle":
                    builders.append(path.relative_to(ROOT).as_posix())
    assert builders == ["services/grounding/app/assemble.py"], builders


def test_fetch_plan_is_not_chosen_by_a_model():
    src = (SERVICES / "grounding" / "app" / "plan.py").read_text(encoding="utf-8")
    for word in ("llm", "generate", "ollama", "gemini"):
        assert word not in src.lower(), f"grounding/app/plan.py mentions {word}"


def test_only_knowledge_resolves_llm_diagnose():
    for svc in PY_SERVICES:
        if svc.name in ("knowledge", "control"):
            continue
        for path, src in sources(svc).items():
            assert "llm_diagnose" not in src, f"{path} resolves llm_diagnose"


def test_services_import_no_other_service():
    for svc in PY_SERVICES:
        for path, src in sources(svc).items():
            assert not any(m == "services" or m.startswith("services.") for m in imports(src)), path
            assert "sys.path" not in src, f"{path} edits sys.path"


def test_each_service_creates_tables_only_in_its_own_schema():
    table = re.compile(r"CREATE (?:TABLE|SEQUENCE|UNIQUE INDEX|INDEX)\s+IF NOT EXISTS\s+(?:\w+\s+ON\s+)?\"?(\w+)\"?\.", re.I)
    for svc in PY_SERVICES:
        owned = OWNED_SCHEMA.get(svc.name)
        for path, src in sources(svc).items():
            for schema in table.findall(src):
                assert schema == owned, f"{path} creates objects in {schema}, but {svc.name} owns {owned}"


def test_no_python_service_touches_public_or_another_services_tables():
    writes = re.compile(r"(?:FROM|JOIN|INTO|UPDATE)\s+\"?(\w+)\"?\.\"?\w+", re.I)
    shared_reads = {"orchestrator": {"cases"}}  # its own schema
    for svc in PY_SERVICES:
        owned = OWNED_SCHEMA.get(svc.name)
        for path, src in sources(svc).items():
            for schema in writes.findall(src):
                assert schema != "public", f"{path} touches public"
                if owned and schema in OWNED_SCHEMA.values():
                    assert schema in {owned} | shared_reads.get(svc.name, set()), \
                        f"{path} reaches into {schema}; {svc.name} owns {owned}"
