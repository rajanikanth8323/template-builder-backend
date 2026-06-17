# backend/src/api/tests.py
# Template test cases — CRUD + run
# Stores tests in template_builder.template_tests table
# Running a test: renders the template with runtime_params, checks
# that all expected_strings appear in the rendered HTML output

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()
logger = logging.getLogger(__name__)


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


# =============================================================================
# Pydantic models
# =============================================================================

class TestCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    runtime_params: Dict[str, Any] = {}
    expected_strings: List[str] = []   # strings that must appear in rendered output
    created_by: str = "dev_user"

class TestResponse(BaseModel):
    test_id: str
    template_id: str
    name: str
    description: Optional[str]
    runtime_params: Dict[str, Any]
    expected_strings: List[str]
    created_by: str
    created_at: Optional[str]

class TestRunResult(BaseModel):
    test_id: str
    name: str
    status: str          # "pass" | "fail" | "error"
    message: str
    checks_passed: int
    checks_total: int
    rendered_html: Optional[str] = None   # first 5000 chars of output for preview


# =============================================================================
# Helper — render template with params (inline, no async job needed for tests)
# =============================================================================

async def render_template_for_test(
    engine: AsyncEngine,
    template_id: str,
    runtime_params: Dict[str, Any],
) -> str:
    """
    Fetch template layout + resolve placeholders using sample_value fallback,
    then render to HTML inline (synchronous, no job queue).
    Returns rendered HTML string.
    """
    # 1. Load template layout
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT layout_json FROM template_builder.templates WHERE template_id = CAST(:tid AS uuid)"),
            {"tid": template_id}
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"Template {template_id} not found")
        layout_json = row[0]
        if isinstance(layout_json, str):
            layout_json = json.loads(layout_json)

    # 2. Resolve placeholder values — runtime_params first, then sample_value
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT p.name, p.sample_value, tp.override_sample_value
            FROM template_builder.template_placeholders tp
            JOIN template_builder.placeholders_registry p
              ON tp.registry_id = p.registry_id
            WHERE tp.template_id = CAST(:tid AS uuid)
        """), {"tid": template_id})
        rows = result.fetchall()

    context: Dict[str, str] = {}
    for row in rows:
        name = row[0]
        sample = row[2] if row[2] is not None else row[1]  # override or registry sample
        context[name] = runtime_params.get(name, sample or f"{{{{{name}}}}}")

    # Also add any runtime_params directly (even if not in registry)
    for k, v in runtime_params.items():
        context[k] = str(v)

    # 3. Render HTML using the same logic as html.py renderer
    blocks = layout_json.get("blocks", [])
    html_parts = []

    for block in blocks:
        btype = block.get("type", "")
        if btype == "text":
            content = block.get("content", "")
            resolved = _replace_tokens(content, context)
            for line in [l for l in resolved.split("\n") if l.strip()]:
                html_parts.append(f'<p style="margin:0 0 8px;line-height:1.7;">{line}</p>')

        elif btype == "section":
            label = _replace_tokens(block.get("content", "Section"), context)
            html_parts.append(
                f'<div style="margin:16px 0 8px;font-weight:700;color:#4c1d95;'
                f'font-size:13px;text-transform:uppercase;">{label}</div>'
            )

        elif btype == "table":
            cols = block.get("columns", [])
            rows = block.get("rows", [])
            if cols:
                headers = "".join(f'<th style="padding:8px 12px;text-align:left;">{c.get("header","")}</th>' for c in cols)
                binding_cells = "".join(
                    f'<td style="padding:8px 12px;">{_replace_tokens(c.get("binding",""), context)}</td>'
                    for c in cols
                )
                data_rows = ""
                for row in rows:
                    cells = "".join(
                        f'<td style="padding:8px 12px;">{_replace_tokens(row[i] if i < len(row) else "", context)}</td>'
                        for i, _ in enumerate(cols)
                    )
                    data_rows += f"<tr>{cells}</tr>"
                html_parts.append(
                    f'<table style="width:100%;border-collapse:collapse;margin-bottom:12px;">'
                    f'<thead><tr>{headers}</tr></thead>'
                    f'<tbody><tr>{binding_cells}</tr>{data_rows}</tbody></table>'
                )

        elif btype == "image":
            src = block.get("src", "")
            if src:
                html_parts.append(f'<img src="{src}" style="max-width:100%;" />')

    return "\n".join(html_parts)


def _replace_tokens(content: str, context: Dict[str, str]) -> str:
    if not content:
        return ""
    for key, val in context.items():
        content = content.replace("{{" + key + "}}", str(val) if val is not None else "")
    return content


# =============================================================================
# CRUD endpoints
# =============================================================================

@router.get("/templates/{template_id}/tests", response_model=List[TestResponse])
async def list_tests(template_id: str, request: Request):
    """List all test cases for a template."""
    engine = get_engine(request)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT test_id, template_id, name, description,
                   runtime_params, expected_checks, created_by, created_at
            FROM template_builder.template_tests
            WHERE template_id = CAST(:tid AS uuid)
            ORDER BY created_at ASC
        """), {"tid": template_id})
        rows = result.fetchall()

    return [
        TestResponse(
            test_id=str(r[0]),
            template_id=str(r[1]),
            name=r[2],
            description=r[3] or "",
            runtime_params=r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
            expected_strings=(r[5] or {}).get("strings", []) if r[5] else [],
            created_by=r[6],
            created_at=r[7].isoformat() if r[7] else None,
        )
        for r in rows
    ]


@router.post("/templates/{template_id}/tests", response_model=TestResponse, status_code=201)
async def create_test(template_id: str, req: TestCreateRequest, request: Request):
    """Create a new test case."""
    engine = get_engine(request)
    test_id = str(uuid.uuid4())

    async with engine.begin() as conn:
        # Verify template exists
        chk = await conn.execute(
            text("SELECT 1 FROM template_builder.templates WHERE template_id = CAST(:tid AS uuid)"),
            {"tid": template_id}
        )
        if not chk.fetchone():
            raise HTTPException(status_code=404, detail="Template not found")

        await conn.execute(text("""
            INSERT INTO template_builder.template_tests
                (test_id, template_id, name, description, runtime_params, expected_checks, created_by, created_at)
            VALUES
                (CAST(:test_id AS uuid), CAST(:tid AS uuid), :name, :desc,
                 CAST(:params AS jsonb), CAST(:checks AS jsonb), :created_by, NOW())
        """), {
            "test_id": test_id,
            "tid": template_id,
            "name": req.name,
            "desc": req.description or "",
            "params": json.dumps(req.runtime_params),
            "checks": json.dumps({"strings": req.expected_strings}),
            "created_by": req.created_by,
        })

    return TestResponse(
        test_id=test_id,
        template_id=template_id,
        name=req.name,
        description=req.description,
        runtime_params=req.runtime_params,
        expected_strings=req.expected_strings,
        created_by=req.created_by,
        created_at=None,
    )


@router.put("/templates/{template_id}/tests/{test_id}", response_model=TestResponse)
async def update_test(template_id: str, test_id: str, req: TestCreateRequest, request: Request):
    """Update an existing test case."""
    engine = get_engine(request)
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            UPDATE template_builder.template_tests
            SET name = :name, description = :desc,
                runtime_params = CAST(:params AS jsonb),
                expected_checks = CAST(:checks AS jsonb)
            WHERE test_id = CAST(:test_id AS uuid)
              AND template_id = CAST(:tid AS uuid)
            RETURNING test_id, template_id, name, description,
                      runtime_params, expected_checks, created_by, created_at
        """), {
            "test_id": test_id,
            "tid": template_id,
            "name": req.name,
            "desc": req.description or "",
            "params": json.dumps(req.runtime_params),
            "checks": json.dumps({"strings": req.expected_strings}),
        })
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Test not found")

    return TestResponse(
        test_id=str(row[0]),
        template_id=str(row[1]),
        name=row[2],
        description=row[3],
        runtime_params=row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
        expected_strings=(row[5] or {}).get("strings", []) if row[5] else [],
        created_by=row[6],
        created_at=row[7].isoformat() if row[7] else None,
    )


@router.delete("/templates/{template_id}/tests/{test_id}", status_code=204)
async def delete_test(template_id: str, test_id: str, request: Request):
    """Delete a test case."""
    engine = get_engine(request)
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            DELETE FROM template_builder.template_tests
            WHERE test_id = CAST(:test_id AS uuid)
              AND template_id = CAST(:tid AS uuid)
        """), {"test_id": test_id, "tid": template_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Test not found")


# =============================================================================
# Run a single test
# =============================================================================

@router.post("/templates/{template_id}/tests/{test_id}/run", response_model=TestRunResult)
async def run_test(template_id: str, test_id: str, request: Request):
    """
    Run a single test case:
    1. Render the template with runtime_params
    2. Check that all expected_strings appear in the HTML output
    3. Return pass/fail with details
    """
    engine = get_engine(request)

    # Load test
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT test_id, name, runtime_params, expected_checks
            FROM template_builder.template_tests
            WHERE test_id = CAST(:test_id AS uuid)
              AND template_id = CAST(:tid AS uuid)
        """), {"test_id": test_id, "tid": template_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Test not found")

    t_id, t_name, params, checks = row
    runtime_params = params if isinstance(params, dict) else json.loads(params or "{}")
    expected_strings = (checks or {}).get("strings", []) if checks else []

    # Render template
    try:
        rendered_html = await render_template_for_test(engine, template_id, runtime_params)
    except Exception as exc:
        return TestRunResult(
            test_id=test_id,
            name=t_name,
            status="error",
            message=f"Render failed: {str(exc)}",
            checks_passed=0,
            checks_total=len(expected_strings),
        )

    # Check expected strings in FULL rendered output (not truncated)
    if not expected_strings:
        return TestRunResult(
            test_id=test_id,
            name=t_name,
            status="pass",
            message="Document rendered successfully. No string checks defined.",
            checks_passed=0,
            checks_total=0,
            rendered_html=rendered_html[:5000] if rendered_html else "",
        )

    passed = []
    failed = []
    # Check against full HTML — truncation only affects preview display
    full_html = rendered_html  
    for s in expected_strings:
        if s.strip() and s.strip() in full_html:
            passed.append(s)
        else:
            failed.append(s)

    if failed:
        return TestRunResult(
            test_id=test_id,
            name=t_name,
            status="fail",
            message=f"Missing in output: {', '.join(repr(f) for f in failed)}",
            checks_passed=len(passed),
            checks_total=len(expected_strings),
            rendered_html=rendered_html[:5000],
        )

    return TestRunResult(
        test_id=test_id,
        name=t_name,
        status="pass",
        message=f"All {len(passed)} check(s) passed.",
        checks_passed=len(passed),
        checks_total=len(expected_strings),
        rendered_html=rendered_html[:5000],
    )


# =============================================================================
# Run ALL tests for a template
# =============================================================================

@router.post("/templates/{template_id}/tests/run-all")
async def run_all_tests(template_id: str, request: Request):
    """Run all test cases for a template and return a summary."""
    engine = get_engine(request)

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT test_id FROM template_builder.template_tests
            WHERE template_id = CAST(:tid AS uuid)
            ORDER BY created_at ASC
        """), {"tid": template_id})
        test_ids = [str(r[0]) for r in result.fetchall()]

    if not test_ids:
        return {"message": "No tests found", "results": [], "summary": {"pass": 0, "fail": 0, "error": 0}}

    results = []
    for tid in test_ids:
        result = await run_test(template_id, tid, request)
        results.append(result)

    summary = {
        "pass":  sum(1 for r in results if r.status == "pass"),
        "fail":  sum(1 for r in results if r.status == "fail"),
        "error": sum(1 for r in results if r.status == "error"),
        "total": len(results),
    }

    return {"results": results, "summary": summary}