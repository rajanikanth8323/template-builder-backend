const UI_BASE = "/ui";

export const uiService = {
  getDatasources: () => fetch(`${UI_BASE}/datasources`).then((r) => r.json()),
  getFields: (datasourceId) => fetch(`${UI_BASE}/datasources/${datasourceId}/fields`).then((r) => r.json()),
  previewTemplate: (templateId, locale, params) =>
    fetch(`${UI_BASE}/templates/${templateId}/preview`, { method: "POST", body: JSON.stringify({ locale, runtime_params: params }) }).then((r) => r.json()),
};
