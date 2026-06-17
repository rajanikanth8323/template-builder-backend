from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Enum,
    JSON,
    Integer,
    ForeignKey,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import UUID
import uuid
from .db import Base

SCHEMA = "template_builder"


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = {"schema": SCHEMA}

    template_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
        )
    name = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(
        String,
        nullable=False,
        default="draft",
    )  # in Phase 1: draft, published, archived
    output_target = Column(
        String,
        nullable=False,
    )  # 'html','docx','pdf','xlsx','md'
    layout_json = Column(JSON, nullable=False)
    default_locale = Column(String, nullable=False, default="en")
    supported_locales = Column(ARRAY(String), nullable=False, default=["en"])
    industry = Column(String)
    tags = Column(ARRAY(String))
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = {"schema": SCHEMA}

    version_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.templates.template_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    layout_json = Column(JSON, nullable=False)
    output_target = Column(String, nullable=False)
    change_summary = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PlaceholderRegistry(Base):
    __tablename__ = "placeholders_registry"
    __table_args__ = {"schema": SCHEMA}

    registry_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name = Column(Text, nullable=False, unique=True)
    description = Column(Text)
    generation_mode = Column(String, nullable=False, default="manual_sql")
    prompt = Column(Text)      # not used in Phase 1
    sql_text = Column(Text)    # used in Phase 1
    datasource_id = Column(Integer, nullable=False)
    value_type = Column(String, nullable=False, default="string")
    cardinality = Column(String, nullable=False, default="scalar")
    classification = Column(String, nullable=False, default="internal")
    format_json = Column(JSON)
    sample_value = Column(Text)
    metadata = Column(JSON)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TemplatePlaceholder(Base):
    __tablename__ = "template_placeholders"
    __table_args__ = {"schema": SCHEMA}

    template_placeholder_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.templates.template_id", ondelete="CASCADE"),
        nullable=False,
    )
    registry_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.placeholders_registry.registry_id"),
        nullable=False,
    )
    override_prompt = Column(Text)
    override_sql_text = Column(Text)
    override_format = Column(JSON)
    override_datasource_id = Column(Integer)
    override_sample_value = Column(Text)
    metadata = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RenderJob(Base):
    __tablename__ = "render_jobs"
    __table_args__ = {"schema": SCHEMA}

    job_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.templates.template_id"),
        nullable=False,
    )
    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.template_versions.version_id"),
        nullable=True,
    )
    status = Column(String, nullable=False, default="queued")
    output_target = Column(String, nullable=False)
    locale = Column(String, nullable=False)
    runtime_params = Column(JSON)
    result_location = Column(Text)
    logs = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
