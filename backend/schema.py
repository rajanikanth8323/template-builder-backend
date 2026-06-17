from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# ------------------------------
# Template schemas
# ------------------------------
class TemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    output_target: str
    layout_json: Dict[str, Any]
    default_locale: str = "en"
    supported_locales: List[str] = Field(default_factory=lambda: ["en"])
    industry: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class TemplateCreate(TemplateBase):
    created_by: str


class TemplateUpdate(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    layout_json: Optional[Dict[str, Any]] = None
    supported_locales: Optional[List[str]] = None
    industry: Optional[str] = None
    tags: Optional[List[str]] = None


class TemplateOut(TemplateBase):
    template_id: UUID
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ------------------------------
# Template version
# ------------------------------
class TemplateVersionOut(BaseModel):
    version_id: UUID
    template_id: UUID
    version_number: int
    layout_json: Dict[str, Any]
    output_target: str
    change_summary: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PublishRequest(BaseModel):
    change_summary: Optional[str] = None


# ------------------------------
# Placeholder registry
# ------------------------------
class PlaceholderRegistryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    generation_mode: str = "manual_sql"
    sql_text: str
    datasource_id: int
    value_type: str = "string"
    cardinality: str = "scalar"
    classification: str = "internal"
    format_json: Optional[Dict[str, Any]] = None
    sample_value: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_by: str


class PlaceholderRegistryOut(BaseModel):
    registry_id: UUID
    name: str
    description: Optional[str]
    generation_mode: str
    sql_text: Optional[str]
    datasource_id: int
    value_type: str
    cardinality: str
    classification: str
    format_json: Optional[Dict[str, Any]]
    sample_value: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ------------------------------
# Template placeholder binding
# ------------------------------
class TemplatePlaceholderBindingCreate(BaseModel):
    registry_id: UUID
    override_sql_text: Optional[str] = None
    override_format: Optional[Dict[str, Any]] = None
    override_datasource_id: Optional[int] = None
    override_sample_value: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TemplatePlaceholderBindingOut(BaseModel):
    template_placeholder_id: UUID
    template_id: UUID
    registry_id: UUID
    override_sql_text: Optional[str]
    override_format: Optional[Dict[str, Any]]
    override_datasource_id: Optional[int]
    override_sample_value: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True


# ------------------------------
# Document generation
# ------------------------------
class DocumentGenerateRequest(BaseModel):
    template_id: UUID
    version_id: Optional[UUID] = None
    locale: str = "en"
    output_target: str
    runtime_params: Dict[str, Any] = Field(default_factory=dict)


class DocumentGenerateSyncResponse(BaseModel):
    status: str = "success"
    output_target: str
    content: str  # for Phase 1: plain text/HTML (no base64 complicating things)


class RenderJobStatus(BaseModel):
    job_id: UUID
    status: str
    output_target: str
    locale: str
    result_location: Optional[str]
    logs: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
