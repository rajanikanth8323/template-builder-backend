# # src/core/renderers/pdf.py
# # PDF renderer using ReportLab
# # Supports align, fontSize, and table repeat from context.datasets

# import json
# import re
# import os
# from typing import Any, Dict, List
# from io import BytesIO

# from reportlab.lib.pagesizes import A4
# from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
# from reportlab.lib.units import cm
# from reportlab.lib import colors
# from reportlab.platypus import (
#     SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
# )
# from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
# from reportlab.pdfbase import pdfmetrics
# from reportlab.pdfbase.ttfonts import TTFont

# FREESANS_PATH      = '/usr/share/fonts/truetype/freefont/FreeSans.ttf'
# FREESANS_BOLD_PATH = '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf'

# _BODY_FONT = 'Helvetica'
# _BOLD_FONT = 'Helvetica-Bold'

# if os.path.exists(FREESANS_PATH):
#     pdfmetrics.registerFont(TTFont('FreeSans', FREESANS_PATH))
#     _BODY_FONT = 'FreeSans'

# if os.path.exists(FREESANS_BOLD_PATH):
#     pdfmetrics.registerFont(TTFont('FreeSans-Bold', FREESANS_BOLD_PATH))
#     _BOLD_FONT = 'FreeSans-Bold'


# class PdfRenderer:

#     def render(self, layout_json: Any, context: Dict[str, Any]) -> bytes:
#         if isinstance(layout_json, str):
#             layout_json = json.loads(layout_json)

#         buf = BytesIO()
#         doc = SimpleDocTemplate(
#             buf, pagesize=A4,
#             leftMargin=2.5*cm, rightMargin=2.5*cm,
#             topMargin=2*cm,    bottomMargin=2*cm,
#         )

#         styles = self._build_styles()
#         story  = []

#         blocks = layout_json.get("blocks", [])
#         if not blocks:
#             story.append(Paragraph("No content in this template.", styles["body"]))
#         else:
#             for block in blocks:
#                 btype = block.get("type", "")
#                 if btype == "section":
#                     self._add_section(story, block, context, styles)
#                 elif btype == "text":
#                     self._add_text(story, block, context, styles)
#                 elif btype == "table":
#                     self._add_table(story, block, context, styles)
#                 elif btype == "image":
#                     self._add_image(story, block, context, styles)

#         doc.build(story)
#         return buf.getvalue()

#     def _build_styles(self):
#         base = getSampleStyleSheet()
#         return {
#             "body": ParagraphStyle(
#                 "body", parent=base["Normal"],
#                 fontName=_BODY_FONT, fontSize=11, leading=17, spaceAfter=6,
#             ),
#             "section": ParagraphStyle(
#                 "section", parent=base["Normal"],
#                 fontName=_BOLD_FONT, fontSize=11, leading=14,
#                 textColor=colors.HexColor("#4C1D95"),
#                 spaceBefore=14, spaceAfter=4,
#             ),
#             "image_placeholder": ParagraphStyle(
#                 "image_placeholder", parent=base["Normal"],
#                 fontName=_BODY_FONT, fontSize=10,
#                 textColor=colors.HexColor("#94A3B8"),
#             ),
#         }

#     def _add_section(self, story, block, context, styles):
#         content = self._replace_tokens(block.get("content", "Section"), context)
#         story.append(Spacer(1, 6))
#         story.append(Paragraph(content.upper(), styles["section"]))
#         story.append(HRFlowable(
#             width="100%", thickness=1.5,
#             color=colors.HexColor("#A78BFA"), spaceAfter=8
#         ))

#     def _add_text(self, story, block, context, styles):
#         content = self._replace_tokens(block.get("content", ""), context)
#         if not content.strip():
#             return
#         align_map  = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
#         align_val  = block.get("align", "left")
#         font_size  = block.get("fontSize", 14)
#         text_style = ParagraphStyle(
#             "dynamic_text", parent=styles["body"],
#             fontSize=font_size, leading=font_size * 1.4,
#             alignment=align_map.get(align_val, TA_LEFT),
#         )
#         for line in content.split("\n"):
#             if line.strip():
#                 line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
#                 story.append(Paragraph(line, text_style))
#             else:
#                 story.append(Spacer(1, 6))

#     def _add_table(self, story, block, context, styles):
#         cols     = block.get("columns", [])
#         block_id = block.get("block_id", "")

#         if not cols:
#             return

#         story.append(Spacer(1, 8))

#         # Header row
#         header     = [col.get("header", "") for col in cols]
#         table_data = [header]

#         # Check datasets for repeat rows
#         datasets  = context.get("datasets", {})
#         data_rows = datasets.get(block_id, [])

#         if data_rows:
#             # Real dataset rows
#             for row in data_rows:
#                 table_data.append([
#                     str(row[ci]) if ci < len(row) else ""
#                     for ci in range(len(cols))
#                 ])
#         else:
#             # Fallback: binding row + manual rows
#             binding_row = [
#                 self._replace_tokens(col.get("binding", ""), context)
#                 for col in cols
#             ]
#             table_data.append(binding_row)

#             manual_rows = block.get("rows", [])
#             for row in manual_rows:
#                 table_data.append([
#                     self._replace_tokens(row[i] if i < len(row) else "", context)
#                     for i in range(len(cols))
#                 ])

#         page_width = A4[0] - 5*cm
#         col_width  = page_width / len(cols)

#         table = Table(table_data, colWidths=[col_width] * len(cols))
#         table.setStyle(TableStyle([
#             ("BACKGROUND",     (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
#             ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
#             ("FONTNAME",       (0, 0), (-1, 0), _BOLD_FONT),
#             ("FONTSIZE",       (0, 0), (-1, 0), 10),
#             ("ALIGN",          (0, 0), (-1, 0), "LEFT"),
#             ("TOPPADDING",     (0, 0), (-1, 0), 7),
#             ("BOTTOMPADDING",  (0, 0), (-1, 0), 7),
#             ("LEFTPADDING",    (0, 0), (-1, -1), 10),
#             ("FONTNAME",       (0, 1), (-1, -1), _BODY_FONT),
#             ("FONTSIZE",       (0, 1), (-1, -1), 10),
#             ("ALIGN",          (0, 1), (-1, -1), "LEFT"),
#             ("TOPPADDING",     (0, 1), (-1, -1), 6),
#             ("BOTTOMPADDING",  (0, 1), (-1, -1), 6),
#             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
#                 colors.HexColor("#FFFFFF"),
#                 colors.HexColor("#F8FAFC"),
#             ]),
#             ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
#             ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
#         ]))

#         story.append(table)
#         story.append(Spacer(1, 10))

#     def _add_image(self, story, block, context, styles):
#         src = self._replace_tokens(block.get("src", ""), context)
#         if src:
#             story.append(Paragraph(f"[Image: {src}]", styles["image_placeholder"]))
#             story.append(Spacer(1, 6))

#     def _replace_tokens(self, content: str, context: Dict[str, Any]) -> str:
#         if not content:
#             return ""
#         values = context.get("values", {})
#         for key, val in values.items():
#             content = content.replace("{{" + key + "}}", str(val) if val is not None else "")
#         content = re.sub(r'\{\{[^}]+\}\}', '', content)
#         return content.strip()
# src/core/renderers/pdf.py
# PDF renderer using ReportLab
# Supports align, fontSize, and table repeat from context.datasets

import json
import re
import os
import base64
import urllib.request
from typing import Any, Dict, List
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image as RLImage
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FREESANS_PATH      = '/usr/share/fonts/truetype/freefont/FreeSans.ttf'
FREESANS_BOLD_PATH = '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf'

_BODY_FONT = 'Helvetica'
_BOLD_FONT = 'Helvetica-Bold'

if os.path.exists(FREESANS_PATH):
    pdfmetrics.registerFont(TTFont('FreeSans', FREESANS_PATH))
    _BODY_FONT = 'FreeSans'

if os.path.exists(FREESANS_BOLD_PATH):
    pdfmetrics.registerFont(TTFont('FreeSans-Bold', FREESANS_BOLD_PATH))
    _BOLD_FONT = 'FreeSans-Bold'


class PdfRenderer:

    def render(self, layout_json: Any, context: Dict[str, Any]) -> bytes:
        if isinstance(layout_json, str):
            layout_json = json.loads(layout_json)

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=2.5*cm, rightMargin=2.5*cm,
            topMargin=2*cm,    bottomMargin=2*cm,
        )

        styles = self._build_styles()
        story  = []

        blocks = layout_json.get("blocks", [])
        if not blocks:
            story.append(Paragraph("No content in this template.", styles["body"]))
        else:
            for block in blocks:
                btype = block.get("type", "")
                if btype == "section":
                    self._add_section(story, block, context, styles)
                elif btype == "text":
                    self._add_text(story, block, context, styles)
                elif btype == "table":
                    self._add_table(story, block, context, styles)
                elif btype == "image":
                    self._add_image(story, block, context, styles)

        doc.build(story)
        return buf.getvalue()

    def _build_styles(self):
        base = getSampleStyleSheet()
        return {
            "body": ParagraphStyle(
                "body", parent=base["Normal"],
                fontName=_BODY_FONT, fontSize=11, leading=17, spaceAfter=6,
            ),
            "section": ParagraphStyle(
                "section", parent=base["Normal"],
                fontName=_BOLD_FONT, fontSize=11, leading=14,
                textColor=colors.HexColor("#4C1D95"),
                spaceBefore=14, spaceAfter=4,
            ),
            "image_placeholder": ParagraphStyle(
                "image_placeholder", parent=base["Normal"],
                fontName=_BODY_FONT, fontSize=10,
                textColor=colors.HexColor("#94A3B8"),
            ),
        }

    def _add_section(self, story, block, context, styles):
        content = self._replace_tokens(block.get("content", "Section"), context)
        story.append(Spacer(1, 6))
        story.append(Paragraph(content.upper(), styles["section"]))
        story.append(HRFlowable(
            width="100%", thickness=1.5,
            color=colors.HexColor("#A78BFA"), spaceAfter=8
        ))

    def _add_text(self, story, block, context, styles):
        content = self._replace_tokens(block.get("content", ""), context)
        if not content.strip():
            return
        align_map  = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
        align_val  = block.get("align", "left")
        font_size  = block.get("fontSize", 14)
        text_style = ParagraphStyle(
            "dynamic_text", parent=styles["body"],
            fontSize=font_size, leading=font_size * 1.4,
            alignment=align_map.get(align_val, TA_LEFT),
        )
        for line in content.split("\n"):
            if line.strip():
                line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(line, text_style))
            else:
                story.append(Spacer(1, 6))

    def _add_table(self, story, block, context, styles):
        cols     = block.get("columns", [])
        block_id = block.get("block_id", "")

        if not cols:
            return

        story.append(Spacer(1, 8))

        # Header row
        header     = [col.get("header", "") for col in cols]
        table_data = [header]

        # Check datasets for repeat rows
        datasets  = context.get("datasets", {})
        data_rows = datasets.get(block_id, [])

        if data_rows:
            for row in data_rows:
                table_data.append([
                    str(row[ci]) if ci < len(row) else ""
                    for ci in range(len(cols))
                ])
        else:
            binding_row = [
                self._replace_tokens(col.get("binding", ""), context)
                for col in cols
            ]
            table_data.append(binding_row)

            manual_rows = block.get("rows", [])
            for row in manual_rows:
                table_data.append([
                    self._replace_tokens(row[i] if i < len(row) else "", context)
                    for i in range(len(cols))
                ])

        page_width = A4[0] - 5*cm
        col_width  = page_width / len(cols)

        table = Table(table_data, colWidths=[col_width] * len(cols))
        table.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
            ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
            ("FONTNAME",       (0, 0), (-1, 0), _BOLD_FONT),
            ("FONTSIZE",       (0, 0), (-1, 0), 10),
            ("ALIGN",          (0, 0), (-1, 0), "LEFT"),
            ("TOPPADDING",     (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING",  (0, 0), (-1, 0), 7),
            ("LEFTPADDING",    (0, 0), (-1, -1), 10),
            ("FONTNAME",       (0, 1), (-1, -1), _BODY_FONT),
            ("FONTSIZE",       (0, 1), (-1, -1), 10),
            ("ALIGN",          (0, 1), (-1, -1), "LEFT"),
            ("TOPPADDING",     (0, 1), (-1, -1), 6),
            ("BOTTOMPADDING",  (0, 1), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.HexColor("#FFFFFF"),
                colors.HexColor("#F8FAFC"),
            ]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ]))

        story.append(table)
        story.append(Spacer(1, 10))

    def _add_image(self, story, block, context, styles):
        src = self._replace_tokens(block.get("src", ""), context)
        if not src:
            return

        try:
            img_data = self._load_image_bytes(src)
            if img_data:
                img_buf = BytesIO(img_data)
                max_w   = A4[0] - 5 * cm
                rl_img  = RLImage(img_buf)
                rl_img._restrictSize(max_w, A4[1] - 8 * cm)
                story.append(rl_img)
                story.append(Spacer(1, 8))
            else:
                story.append(Paragraph(f"[Image not found: {src}]", styles["image_placeholder"]))
        except Exception as exc:
            story.append(Paragraph(f"[Image error: {exc}]", styles["image_placeholder"]))

        story.append(Spacer(1, 6))

    def _load_image_bytes(self, src: str):
        """Return raw image bytes from a base64 data-URL or http/https URL."""
        if src.startswith("data:"):
            # e.g. data:image/png;base64,AAAA...
            _, encoded = src.split(",", 1)
            return base64.b64decode(encoded)
        elif src.startswith("http://") or src.startswith("https://"):
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        return None

    def _replace_tokens(self, content: str, context: Dict[str, Any]) -> str:
        if not content:
            return ""
        values = context.get("values", {})
        for key, val in values.items():
            content = content.replace("{{" + key + "}}", str(val) if val is not None else "")
        content = re.sub(r'\{\{[^}]+\}\}', '', content)
        return content.strip()