const API_BASE = "/v1";

export const api = {
  getTemplates: () => fetch(`${API_BASE}/templates`).then((r) => r.json()),
  createTemplate: (data) => fetch(`${API_BASE}/templates`, { method: "POST", body: JSON.stringify(data) }).then((r) => r.json()),
  publishTemplate: (id) => fetch(`${API_BASE}/templates/${id}/publish`, { method: "POST" }),
  generateDocument: (data) => fetch(`${API_BASE}/documents/generate`, { method: "POST", body: JSON.stringify(data) }).then((r) => r.json()),
};
