# src/core/renderers/html.py
import json
from typing import Any, Dict, List


class HtmlRenderer:
    """
    Renders a template's layout_json blocks into an HTML string.
    Supports align, fontSize, and table repeat from context.datasets.
    """

    def render(self, layout_json: Any, context: Dict[str, Any]) -> str:
        if isinstance(layout_json, str):
            layout_json = json.loads(layout_json)

        blocks = layout_json.get("blocks", [])
        if not blocks:
            return self._wrap_body("<p>No content in this template.</p>")

        html_parts = []
        for block in blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                html_parts.append(self._render_text(block, context))
            elif block_type == "table":
                html_parts.append(self._render_table(block, context))
            elif block_type == "image":
                html_parts.append(self._render_image(block))
            elif block_type == "section":
                html_parts.append(self._render_section(block, context))

        return self._wrap_body("\n".join(html_parts))

    def _replace_tokens(self, content: str, context: Dict[str, Any]) -> str:
        if not content:
            return ""
        values = context.get("values", {})
        for key, val in values.items():
            content = content.replace("{{" + key + "}}", str(val) if val is not None else "")
        return content

    def _render_text(self, block: Dict, context: Dict) -> str:
        content   = block.get("content", "")
        resolved  = self._replace_tokens(content, context)
        lines     = [line for line in resolved.split("\n") if line.strip()]
        align     = block.get("align", "left")
        font_size = block.get("fontSize", 14)
        return "\n".join(
            f'<p style="margin:0 0 8px;line-height:1.7;text-align:{align};font-size:{font_size}px;">{line}</p>'
            for line in lines
        )

    def _render_table(self, block: Dict, context: Dict) -> str:
        cols     = block.get("columns", [])
        block_id = block.get("block_id", "")

        if not cols:
            return '<p style="color:#94a3b8;">Empty table</p>'

        # Header row
        headers = "".join(
            f'<th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;'
            f'font-size:13px;color:#475569;font-weight:600;">{col.get("header", "")}</th>'
            for col in cols
        )

        # Check if datasets has rows for this block
        datasets    = context.get("datasets", {})
        data_rows   = datasets.get(block_id, [])

        if data_rows:
            # ── Real dataset rows from DB ──────────────────────────
            logger_note = f"<!-- {len(data_rows)} rows from dataset -->"
            trs = ""
            for ri, row in enumerate(data_rows):
                bg    = "#fff" if ri % 2 == 0 else "#f8fafc"
                cells = ""
                for ci, col in enumerate(cols):
                    # Use dataset value if available, else binding token
                    val = row[ci] if ci < len(row) else self._replace_tokens(
                        col.get("binding", ""), context
                    )
                    cells += (
                        f'<td style="padding:8px 12px;font-size:13px;color:#334155;'
                        f'border-bottom:1px solid #f1f5f9;background:{bg};">{val}</td>'
                    )
                trs += f"<tr>{cells}</tr>"
        else:
            # ── Fallback: binding row only ─────────────────────────
            logger_note = "<!-- binding row fallback -->"
            binding_cells = "".join(
                f'<td style="padding:8px 12px;font-size:13px;color:#334155;'
                f'border-bottom:1px solid #f1f5f9;">'
                f'{self._replace_tokens(col.get("binding", ""), context)}</td>'
                for col in cols
            )
            trs = f"<tr>{binding_cells}</tr>"

            # Also render any manually added rows
            manual_rows = block.get("rows", [])
            for ri, row in enumerate(manual_rows):
                cells = ""
                for ci, col in enumerate(cols):
                    cell_val = row[ci] if ci < len(row) and row[ci] else col.get("binding", "")
                    resolved = self._replace_tokens(cell_val, context)
                    bg       = "#fff" if ri % 2 == 0 else "#f8fafc"
                    cells   += (
                        f'<td style="padding:8px 12px;font-size:13px;color:#334155;'
                        f'border-bottom:1px solid #f1f5f9;background:{bg};">{resolved}</td>'
                    )
                trs += f"<tr>{cells}</tr>"

        return f"""
{logger_note}
<table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
  <thead><tr>{headers}</tr></thead>
  <tbody>{trs}</tbody>
</table>"""

    def _render_image(self, block: Dict) -> str:
        src = block.get("src", "")
        if src:
            return f'<img src="{src}" style="max-width:100%;border-radius:6px;margin-bottom:12px;" />'
        return '<div style="height:80px;background:#f1f5f9;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:13px;margin-bottom:12px;">Image placeholder</div>'

    def _render_section(self, block: Dict, context: Dict) -> str:
        label = self._replace_tokens(block.get("content", "Section"), context)
        return (
            f'<div style="display:flex;align-items:center;gap:12px;margin:20px 0 12px;padding:0;">'
            f'<div style="height:2px;width:24px;background:#a78bfa;border-radius:2px;flex-shrink:0;"></div>'
            f'<span style="font-size:13px;font-weight:700;color:#4c1d95;letter-spacing:0.05em;text-transform:uppercase;white-space:nowrap;">{label}</span>'
            f'<div style="flex:1;height:2px;background:#e2e8f0;border-radius:2px;"></div>'
            f'</div>'
        )

    def _wrap_body(self, body: str) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Generated Document</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    color: #1e293b;
    padding: 32px;
    line-height: 1.6;
    background: #ffffff;
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""