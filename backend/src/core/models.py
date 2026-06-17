class Template(Base):
    __tablename__ = "templates"
    template_id = Column(UUID, primary_key=True)
    name = Column(Text)
    description = Column(Text)
    status = Column(Text)
    output_target = Column(Text)
    layout_json = Column(JSONB)
    default_locale = Column(Text)
    supported_locales = Column(ARRAY(Text))
    # NEW: tenant that owns this template
    tenant_id = Column(Text, nullable=False, default="global")

class PlaceholderRegistry(Base):
    __tablename__ = "placeholdersregistry"
    registry_id = Column(UUID, primary_key=True)
    name = Column(Text, unique=True)
    description = Column(Text)
    generationmode = Column(Text)
    sqltext = Column(Text)
    datasource_id = Column(UUID)
    value_type = Column(Text)
    cardinality = Column(Text)
    sample_value = Column(JSONB)
    # NEW: tenant that owns this template
    tenant_id = Column(Text, nullable=False, default="global")

class RenderJob(Base):
    __tablename__ = "renderjobs"
    job_id = Column(UUID, primary_key=True)
    template_id = Column(UUID)
    status = Column(Text)
    output_target = Column(Text)
    locale = Column(Text)
    runtime_params = Column(JSONB)
    result_location = Column(Text)
    # NEW: tenant that owns this template
    tenant_id = Column(Text, nullable=False, default="global")

class UploadedDocument(Base):
    __tablename__ = "uploadeddocuments"
    upload_id = Column(UUID, primary_key=True)
    template_id = Column(UUID)
    original_filename = Column(Text)
    mimetype = Column(Text)
    storage_uri = Column(Text)
    extraction_status = Column(Text)
    extracted_layout = Column(JSONB)
