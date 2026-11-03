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
    entries = []
    for item in toc:
        kind = item.get("kind", "")
        missing = unnamed(item.get("title"), kind)
        page = item.get("physical_page")
        group = (
            "Recipes"
            if kind == "recipe"
            else ("Pages without titles" if missing else "Named sections")
        )
        entries.append(
            (
                {"Recipes": 0, "Named sections": 1, "Pages without titles": 2}[group],
                missing,
                {
                    **item,
                    "title": section_label(
                        item.get("title"), kind, [page] if page else []
                    ),
                    "group": group,
                },
            )
        )
    # Python's stable sort preserves source order inside each group. Order the
    # full metadata list before applying the existing bounded page selection.
    return [item for _, _, item in sorted(entries, key=lambda x: x[:2])]


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
