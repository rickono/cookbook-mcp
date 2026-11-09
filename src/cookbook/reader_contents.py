"""Reader labels and grouping for retained scanned sections; no source writes."""

from html import escape


def unnamed(title, kind):
    return not title or title == f"Untitled {kind.replace('_', ' ')}"


def section_label(title, kind, pages):
    if not unnamed(title, kind):
        return title
    label = (
        ("Page " if len(pages) == 1 else "Pages ") + ", ".join(str(n) for n in pages)
        if pages
        else "Section without a title"
    )
    return label + (" · Recipe" if kind == "recipe" else "")


def scanned_contents(toc):
    # Retain source order, including unnamed pages between recipes.
    return [
        {
            **item,
            "title": section_label(
                item.get("title"),
                item.get("kind", ""),
                [item["physical_page"]] if item.get("physical_page") else [],
            ),
        }
        for item in toc
    ]


def contents_html(data, raw, back, anchor):
    result = []
    group = None
    for item in data["contents"]:
        current = item.get("group")
        if current != group:
            if group:
                result.append(
                    "</nav></details>" if group == "Pages without titles" else "</nav>"
                )
            group = current
            if group == "Pages without titles":
                result.append(
                    '<details class="unnamed-pages"><summary>Pages without titles</summary><nav aria-label="Pages without titles">'
                )
            elif group:
                result.append(
                    "<h2>"
                    + escape(group)
                    + '</h2><nav aria-label="'
                    + escape(group)
                    + '">'
                )
        result.append(
            anchor(item["at"], item["title"], back=raw)
            if item.get("at")
            else "<p>" + escape(item["title"]) + " — source target unresolved</p>"
        )
    if group:
        result.append(
            "</nav></details>" if group == "Pages without titles" else "</nav>"
        )
    if data["next_contents"]:
        result.append(anchor(data["next_contents"], "More contents", back=back))
    return "".join(result)
