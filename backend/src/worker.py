# src/worker.py
# ---------------------------------------------------------------------
# Production‑grade async job processor for template_builder.render_jobs
# Supports concurrent rendering within a single worker + horizontal scaling
# ---------------------------------------------------------------------

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager

# ---------------------------------------------------------------------
# Configuration (override via env vars)
# ---------------------------------------------------------------------
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@db:5432/template_builder",
)
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/app/results"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT_RENDERS = int(os.getenv("MAX_CONCURRENT_RENDERS", "3"))
POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL_SEC", "5.0"))
PDF_CONCURRENCY = int(os.getenv("PDF_CONCURRENCY", "2"))  # shared browser pool limit

# ---------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Database session manager
# ---------------------------------------------------------------------
class Database:
    """Wraps an async SQLAlchemy engine and provides a scoped session."""

    def __init__(self, db_url: str):
        self.engine: AsyncEngine = create_async_engine(
            db_url,
            echo=False,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @asynccontextmanager
    async def session(self):
        """Yield a transactional session with automatic rollback on exception."""
        async with self.session_factory() as session:
            async with session.begin():
                try:
                    yield session
                except Exception:
                    logger.exception("Session encountered an error, rolling back")
                    raise

    async def close(self):
        await self.engine.dispose()


db = Database(DB_URL)

# ---------------------------------------------------------------------
# Renderer plugins (Phase 1: skeleton implementations)
# ---------------------------------------------------------------------
class Renderer:
    """Base class for pluggable renderers. Each subclass handles one output format."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path

    async def render(self, template_id: str, context: Dict[str, Any], locale: str) -> Path:
        """Render the template and return the artifact path."""
        raise NotImplementedError


class HTMLRenderer(Renderer):
    async def render(self, template_id: str, context: Dict[str, Any], locale: str,
                     layout_json: Any = None) -> Path:
        from core.renderers.html import HtmlRenderer
        artifact = self.storage_path / f"{template_id}_{locale}.html"
        html_str = HtmlRenderer().render(layout_json or {}, context)
        artifact.write_text(html_str, encoding="utf-8")
        return artifact


class PDFRenderer(Renderer):
    def __init__(self, storage_path: Path, max_concurrency: int):
        super().__init__(storage_path)
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def render(self, template_id: str, context: Dict[str, Any], locale: str,
                     layout_json: Any = None) -> Path:
        async with self.semaphore:
            from core.renderers.pdf import PdfRenderer
            artifact = self.storage_path / f"{template_id}_{locale}.pdf"
            pdf_bytes = await asyncio.get_event_loop().run_in_executor(
                None, PdfRenderer().render, layout_json or {}, context
            )
            artifact.write_bytes(pdf_bytes)
            return artifact


class DocxRendererPlugin(Renderer):
    async def render(self, template_id: str, context: Dict[str, Any], locale: str,
                     layout_json: Any = None) -> Path:
        from core.renderers.docx import DocxRenderer
        artifact = self.storage_path / f"{template_id}_{locale}.docx"
        docx_bytes = DocxRenderer().render(layout_json or {}, context)
        artifact.write_bytes(docx_bytes)
        return artifact


# Registry of renderers (add real implementations later)
RENDERERS = {
    "html": HTMLRenderer(RESULTS_DIR),
    "pdf":  PDFRenderer(RESULTS_DIR, PDF_CONCURRENCY),
    "docx": DocxRendererPlugin(RESULTS_DIR),
    "xlsx": HTMLRenderer(RESULTS_DIR),   # real xlsx renderer coming next
    "md":   HTMLRenderer(RESULTS_DIR),   # real md renderer coming next
}

# ---------------------------------------------------------------------
# Resolver engine (placeholder resolution)
# ---------------------------------------------------------------------
async def resolve_placeholders(
    session: AsyncSession, template_id: str, runtime_params: Dict[str, Any]
) -> Dict[str, Any]:
    """Fetch bound placeholders, resolve values, and return the render context."""
    bind_sql = text(
        """
        SELECT p.name,
               p.generation_mode,
               p.prompt,
               p.format_json,
               p.datasource_id,
               p.sample_value,
               tp.override_prompt,
               tp.override_format
        FROM template_builder.template_placeholders tp
        JOIN template_builder.placeholders_registry p
          ON tp.registry_id = p.registry_id
        WHERE tp.template_id = :tid;
        """
    )
    result = await session.execute(bind_sql, {"tid": template_id})
    bindings = result.fetchall()

    context: Dict[str, Any] = {"values": {}, "datasets": {}}
    datasource_groups: Dict[Optional[str], list] = {}

    for row in bindings:
        ds_id = row.datasource_id
        datasource_groups.setdefault(ds_id, []).append(row)

    for ds_id, placeholders in datasource_groups.items():
        logger.info(f"Resolving {len(placeholders)} placeholders for datasource {ds_id}")
        for ph in placeholders:
            name = ph.name
            # Prefer runtime param, fall back to sample value
            context["values"][name] = runtime_params.get(name, ph.sample_value)

    return context

# ---------------------------------------------------------------------
# Helper: audit insertion from the worker
# ---------------------------------------------------------------------
async def log_worker_audit(
    session: AsyncSession,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict,
) -> None:
    """Insert a row into template_builder.audit_events from the worker."""
    audit_sql = text(
        """
        INSERT INTO template_builder.audit_events
            (entity_type, entity_id, action, actor, details_json, created_at)
        VALUES
            (:etype, :eid, :act, 'worker', :details, now());
        """
    )
    await session.execute(
        audit_sql,
        {
            "etype": entity_type,
            "eid": entity_id,
            "act": action,
            # `default=str` converts UUIDs (or any non‑JSON type) to strings
            "details": json.dumps(details, default=str),
        },
    )


# ---------------------------------------------------------------------
# Single job processor with concurrency control
# ---------------------------------------------------------------------
class JobProcessor:
    def __init__(self, db: Database, max_concurrent: int):
        self.db = db
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_jobs: Dict[str, asyncio.Task] = {}

    async def process_one(self) -> bool:
        """Atomically claim and process one queued job. Returns True if a job was found."""
        async with self.db.session() as session:
            claim_sql = text(
                """
                UPDATE template_builder.render_jobs
                SET status = 'running', updated_at = now()
                WHERE job_id = (
                    SELECT job_id
                    FROM template_builder.render_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING job_id,
                          template_id,
                          version_id,
                          output_target,
                          locale,
                          runtime_params;
                """
            )
            result = await session.execute(claim_sql)
            job = result.fetchone()
            if not job:
                logger.debug("No queued jobs available")
                return False

            job_id, template_id, _, output_target, locale, runtime_params = job

            async with self.semaphore:
                task = asyncio.create_task(
                    self._render_job(
                        session,
                        job_id,
                        template_id,
                        output_target,
                        locale,
                        runtime_params,
                    )
                )
                self.active_jobs[job_id] = task

                try:
                    await task
                finally:
                    self.active_jobs.pop(job_id, None)

            return True

    async def _render_job(
        self,
        session: AsyncSession,
        job_id: str,
        template_id: str,
        output_target: str,
        locale: str,
        runtime_params: Any,
    ) -> None:
        """Fetch template, resolve data, render, and update job status."""
        logger.info(
            f"Starting render job {job_id} (template={template_id}, format={output_target})"
        )
        try:
            # -----------------------------------------------------------------
            # Load template layout (placeholder for future use)
            # -----------------------------------------------------------------
            tmpl_sql = text(
                "SELECT layout_json FROM template_builder.templates WHERE template_id = CAST(:tid AS uuid);"
            )
            result = await session.execute(tmpl_sql, {"tid": template_id})
            template_row = result.fetchone()
            if not template_row:
                raise ValueError(f"Template {template_id} not found")

            # -----------------------------------------------------------------
            # Normalise runtime_params (JSONB may already be a dict)
            # -----------------------------------------------------------------
            if isinstance(runtime_params, (str, bytes)):
                params: Dict[str, Any] = json.loads(runtime_params or "{}")
            elif isinstance(runtime_params, dict):
                params = runtime_params
            else:
                raise TypeError(
                    f"runtime_params must be str, bytes, or dict, got {type(runtime_params)}"
                )

            # -----------------------------------------------------------------
            # Resolve placeholders
            # -----------------------------------------------------------------
            context = await resolve_placeholders(session, template_id, params)

            # -----------------------------------------------------------------
            # Render via the appropriate plugin
            # -----------------------------------------------------------------
            renderer = RENDERERS.get(output_target)
            if not renderer:
                raise ValueError(f"Unsupported output target: {output_target}")

            layout_json = template_row[0]
            if isinstance(layout_json, str):
                layout_json = json.loads(layout_json)
            artifact_path = await renderer.render(template_id, context, locale, layout_json)

            # -----------------------------------------------------------------
            # Mark job as successful
            # -----------------------------------------------------------------
            update_sql = text(
                """
                UPDATE template_builder.render_jobs
                SET status = 'success',
                    result_location = :path,
                    logs = :logs,
                    updated_at = now()
                WHERE job_id = :jid;
                """
            )
            await session.execute(
                update_sql,
                {
                    "path": str(artifact_path),
                    "logs": f"Rendered to {artifact_path}",
                    "jid": job_id,
                },
            )

            # -----------------------------------------------------------------
            # Worker‑side audit (success)
            # -----------------------------------------------------------------
            await log_worker_audit(
                session,
                "render_jobs",
                job_id,
                "complete",
                {
                    "template_id": template_id,
                    "output_target": output_target,
                    "locale": locale,
                    "artifact_path": str(artifact_path),
                },
            )
            await session.commit()
            logger.info(f"Job {job_id} completed successfully -> {artifact_path}")

        except Exception as exc:  # pragma: no cover
            logger.exception(f"Job {job_id} failed")

            # -----------------------------------------------------------------
            # Mark job as error
            # -----------------------------------------------------------------
            error_sql = text(
                """
                UPDATE template_builder.render_jobs
                SET status = 'error',
                    logs = :logs,
                    updated_at = now()
                WHERE job_id = :jid;
                """
            )
            await session.execute(
                error_sql,
                {"logs": str(exc), "jid": job_id},
            )

            # -----------------------------------------------------------------
            # Worker‑side audit (error)
            # -----------------------------------------------------------------
            await log_worker_audit(
                session,
                "render_jobs",
                job_id,
                "error",
                {
                    "template_id": template_id,
                    "error_message": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            await session.commit()

    async def graceful_shutdown(self):
        """Cancel any in‑flight renders and wait for them to finish."""
        if not self.active_jobs:
            return

        logger.warning(f"Cancelling {len(self.active_jobs)} active jobs...")
        for task in self.active_jobs.values():
            task.cancel()
        await asyncio.gather(*self.active_jobs.values(), return_exceptions=True)
        logger.info("All active jobs stopped")


# ---------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------
async def worker_main(processor: JobProcessor, poll_interval: float):
    """Poll indefinitely for queued jobs with graceful shutdown."""
    logger.info(
        f"Worker started (max_concurrent={MAX_CONCURRENT_RENDERS}, "
        f"poll_interval={poll_interval}s, pdf_concurrency={PDF_CONCURRENCY})"
    )
    try:
        while True:
            processed = await processor.process_one()
            if not processed:
                await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        logger.info("Worker received shutdown signal")
        await processor.graceful_shutdown()
    finally:
        await db.close()


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    job_processor = JobProcessor(db, max_concurrent=MAX_CONCURRENT_RENDERS)
    try:
        asyncio.run(worker_main(job_processor, POLL_INTERVAL_SEC))
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        sys.exit(0)