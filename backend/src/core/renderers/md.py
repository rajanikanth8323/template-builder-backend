# # src/core/renderers/md.py
# # Markdown renderer — converts template layout to Markdown

# from typing import Any, Dict


# def _resolve(text: str, values: Dict[str, str]) -> str:
#     if not text:
#         return ""
#     for key, val in values.items():
#         text = text.replace(f"{{{{{key}}}}}", val)
#     return text


# class MdRenderer:
#     def render(self, layout_json: Dict[str, Any], context: Dict[str, Any]) -> str:
#         values   = context.get("values", {})
#         datasets = context.get("datasets", {})
#         blocks   = layout_json.get("blocks", [])

#         lines = []

#         for block in blocks:
#             btype = block.get("type", "")

#             # ── TEXT block ─────────────────────────────────────
#             if btype == "text":
#                 content = _resolve(block.get("content", ""), values)
#                 if content.strip():
#                     lines.append(content)
#                     lines.append("")

#             # ── SECTION block ──────────────────────────────────
#             elif btype == "section":
#                 label = _resolve(block.get("content", "Section"), values)
#                 lines.append(f"## {label}")
#                 lines.append("")

#             # ── TABLE block ────────────────────────────────────
#             elif btype == "table":
#                 columns  = block.get("columns", [])
#                 block_id = block.get("block_id", "")
#                 dataset  = datasets.get(block_id, [])

#                 if not columns:
#                     continue

#                 # Header row
#                 headers = [col.get("header", f"Col {i+1}") for i, col in enumerate(columns)]
#                 lines.append("| " + " | ".join(headers) + " |")
#                 lines.append("| " + " | ".join(["---"] * len(columns)) + " |")

#                 # Data rows from dataset
#                 if dataset:
#                     for data_row in dataset:
#                         cells = []
#                         for ci in range(len(columns)):
#                             val = data_row[ci] if ci < len(data_row) else ""
#                             cells.append(str(val).replace("|", "\\|"))
#                         lines.append("| " + " | ".join(cells) + " |")
#                 else:
#                     # Use binding row — resolve {{tokens}} with actual values
#                     cells = []
#                     for col in columns:
#                         binding = col.get("binding", "")
#                         resolved = _resolve(binding, values)
#                         cells.append(resolved.replace("|", "\\|"))
#                     lines.append("| " + " | ".join(cells) + " |")
#                     # Also add any manual rows
#                     for row in block.get("rows", []):
#                         row_cells = []
#                         for ci, col in enumerate(columns):
#                             val = row[ci] if ci < len(row) else ""
#                             resolved = _resolve(val, values) if val else _resolve(col.get("binding", ""), values)
#                             row_cells.append(resolved.replace("|", "\\|"))
#                         lines.append("| " + " | ".join(row_cells) + " |")

#                 lines.append("")

#             # ── IMAGE block ────────────────────────────────────
#             elif btype == "image":
#                 src = block.get("src", "")
#                 if src:
#                     lines.append(f"![Image]({src})")
#                     lines.append("")

#         return "\n".join(lines)


# src/core/renderers/md.py
# Markdown renderer — converts template layout to Markdown

from typing import Any, Dict


def _resolve(text: str, values: Dict[str, str]) -> str:
    if not text:
        return ""
    for key, val in values.items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text


class MdRenderer:
    def render(self, layout_json: Dict[str, Any], context: Dict[str, Any]) -> str:
        values   = context.get("values", {})
        datasets = context.get("datasets", {})
        blocks   = layout_json.get("blocks", [])

        lines = []

        for block in blocks:
            btype = block.get("type", "")

            # ── TEXT block ─────────────────────────────────────
            if btype == "text":
                content = _resolve(block.get("content", ""), values)
                if content.strip():
                    lines.append(content)
                    lines.append("")

            # ── SECTION block ──────────────────────────────────
            elif btype == "section":
                label = _resolve(block.get("content", "Section"), values)
                lines.append(f"## {label}")
                lines.append("")

            # ── TABLE block ────────────────────────────────────
            elif btype == "table":
                columns  = block.get("columns", [])
                block_id = block.get("block_id", "")
                dataset  = datasets.get(block_id, [])

                if not columns:
                    continue

                # Header row
                headers = [col.get("header", f"Col {i+1}") for i, col in enumerate(columns)]
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(columns)) + " |")

                # Data rows from dataset
                if dataset:
                    for data_row in dataset:
                        cells = []
                        for ci in range(len(columns)):
                            val = data_row[ci] if ci < len(data_row) else ""
                            cells.append(str(val).replace("|", "\\|"))
                        lines.append("| " + " | ".join(cells) + " |")
                else:
                    # Use binding row — resolve {{tokens}} with actual values
                    cells = []
                    for col in columns:
                        binding = col.get("binding", "")
                        resolved = _resolve(binding, values)
                        cells.append(resolved.replace("|", "\\|"))
                    lines.append("| " + " | ".join(cells) + " |")
                    # Also add any manual rows
                    for row in block.get("rows", []):
                        row_cells = []
                        for ci, col in enumerate(columns):
                            val = row[ci] if ci < len(row) else ""
                            resolved = _resolve(val, values) if val else _resolve(col.get("binding", ""), values)
                            row_cells.append(resolved.replace("|", "\\|"))
                        lines.append("| " + " | ".join(row_cells) + " |")

                lines.append("")

            # ── IMAGE block ────────────────────────────────────
            elif btype == "image":
                # Resolve any {{placeholder}} tokens in the src
                src = _resolve(block.get("src", ""), values)
                if src:
                    lines.append(f"![Image]({src})")
                    lines.append("")

        return "\n".join(lines)