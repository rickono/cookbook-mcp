"""Escaped bounded text projection shared by reading and original comparison."""

from html import escape


def text_html(data):
    blocks = data.get("text_blocks") or [
        {"kind": "text", "text": data.get("text", "Text unavailable.")}
    ]
    result = []
    for block in blocks:
        text = '<div class="source-text">' + escape(block["text"]) + "</div>"
        if block["kind"] == "table":
            text = (
                '<p class="table-label">Table excerpt — authored cell boundaries; scroll horizontally. A delivery may start or end inside a table.</p>'
                '<div class="table-region" role="region" tabindex="0" aria-label="Table excerpt, scroll horizontally">'
                + text
                + "</div>"
            )
        result.append(text)
    return "".join(result)
