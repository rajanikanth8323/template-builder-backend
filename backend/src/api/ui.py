router = APIRouter()

def list_datasources(db, tenant_id: str):
    rows = db.execute(
        """
        SELECT datasource_id, name, datasourcetype
        FROM eivs.datasources
        WHERE is_active = true AND tenant_id = :tenant_id
        """,
        {"tenant_id": tenant_id},
    ).fetchall()
    return rows

def get_fields(datasource_id):
    row = db.execute("SELECT semanticmodelyaml FROM eivs.datasources WHERE datasource_id = :id", {"id": datasource_id}).fetchone()
    return yaml.safe_load(row.semanticmodelyaml)

def preview_template(template_id, payload):
    executor = DocumentExecutor()
    html = executor.preview(template_id, payload.locale, payload.runtime_params)
    return {"preview_html": html}
