"""Browser projection of the existing bounded native BookModel contract."""

import hashlib

from .storage import IntegrityError, canonical


def read_native(library, loc):
    from .reader_content import encode_location, move

    pub, bid = loc["publication_id"], loc["book_id"]
    structure = library.get_book_structure(
        pub, bid, offset=loc.get("contents_offset", 0)
    )
    citation = structure["citation"]
    if (
        citation["source_id"] != loc["source_id"]
        or loc.get("model_snapshot_id", citation["model_snapshot_id"])
        != citation["model_snapshot_id"]
    ):
        raise IntegrityError("native identity mismatch")
    base = {
        k: citation[k]
        for k in ("publication_id", "book_id", "source_id", "model_snapshot_id")
    }
    base["contents_offset"] = loc.get("contents_offset", 0)
    data = {
        "citation": citation,
        "state": "contents",
        "contents": [],
        "next_contents": None,
        "adjacent": [],
    }
    for nav in structure["navigation"]:
        data["contents"].append(
            {
                "title": nav["label"],
                "at": encode_location({**base, "target_id": nav["id"]})
                if nav["target"]["state"] == "resolved_node"
                else None,
            }
        )
    for occurrence in structure["reading_order"]:
        data["contents"].append(
            {
                "title": "Source document " + str(occurrence["ordinal"] + 1),
                "at": encode_location({**base, "target_id": occurrence["id"]}),
            }
        )
    more = [
        n
        for n in (structure["next_offset"], structure["next_navigation_offset"])
        if n is not None
    ]
    if more:
        data["next_contents"] = move(
            loc,
            contents_offset=min(more),
            model_snapshot_id=citation["model_snapshot_id"],
        )
    if not loc.get("target_id"):
        return data
    result = library.read_book_content(
        pub,
        bid,
        loc["target_id"],
        cursor=loc.get("cursor"),
        related_offset=loc.get("related_offset", 0),
        byte_budget=60000,
        node_budget=300,
        _reader=True,
    )
    data.update(result)
    if result.get("selection_title"):
        data["citation"]["section_title"] = result["selection_title"]
    data["text_blocks"] = project_blocks(library, pub, result["nodes"])
    data["text"] = "".join(b["text"] for b in data["text_blocks"])
    data["state"] = "partial_text" if result["next_cursor"] else "complete_text"
    data["text_offset"] = loc.get("offset", 0)
    data["structure_notes"] = [
        "Table cell spans "
        + str(item["node"].get("table_row_span") or 1)
        + " rows and "
        + str(item["node"].get("table_column_span") or 1)
        + " columns."
        for item in result["nodes"]
        if item["node"].get("content_kind") == "table_cell"
        and (
            (item["node"].get("table_row_span") or 1) > 1
            or (item["node"].get("table_column_span") or 1) > 1
        )
    ]
    data["next_text"] = (
        move(
            {**loc, **base},
            cursor=result["next_cursor"],
            offset=loc.get("offset", 0) + max(1, len(data["text"])),
        )
        if result["next_cursor"]
        else None
    )
    # The native API requires related pagination without a source cursor. Its
    # own text response stays bounded; it never substitutes for the cursor text.
    related = (
        result
        if not loc.get("cursor")
        else library.read_book_content(
            pub,
            bid,
            loc["target_id"],
            related_offset=loc.get("related_offset", 0),
            node_budget=1,
            _reader=True,
        )
    )
    data["related"] = [
        {
            "label": r["kind"] + " · " + r["state"],
            "at": encode_location({**base, "target_id": r["id"]}),
        }
        for r in related.get("related_records", [])
    ]
    data["references"] = []
    for item in result["nodes"]:
        for index, link in enumerate(item.get("source_links", [])):
            reference_id = hashlib.sha256(
                canonical([item["node"]["id"], index, link])
            ).hexdigest()
            target = link["target"]
            if target["state"] == "resolved_node":
                data["references"].append(
                    {
                        "id": reference_id,
                        "label": "Authored source reference",
                        "at": encode_location({**base, "target_id": target["node_id"]}),
                    }
                )
            else:
                data["references"].append(
                    {
                        "id": reference_id,
                        "label": "Source reference: " + target["state"],
                        "at": None,
                    }
                )
    data["next_related"] = (
        move({**loc, **base}, related_offset=related["next_related_offset"])
        if related.get("next_related_offset") is not None
        else None
    )
    occurrences = structure["reading_order"]
    ids = [o["id"] for o in occurrences]
    if loc["target_id"] in ids:
        i = ids.index(loc["target_id"])
        for n, label in (
            (i - 1, "Previous reading occurrence"),
            (i + 1, "Next reading occurrence"),
        ):
            if 0 <= n < len(ids):
                data["adjacent"].append(
                    {
                        "label": label,
                        "at": encode_location({**base, "target_id": ids[n]}),
                    }
                )
    # Interpretation states and source coverage are not complete-content approval.
    data["citation"]["eligibility"] = {
        "eligible": False,
        "reasons": ["complete_content_approval_not_recorded"],
    }
    data["citation"]["locator"] = {
        "source_parts": result["citations"],
        "coverage": result["coverage"],
        "entity_state": (related.get("entity") or {}).get("state"),
    }
    return data


def project_text(nodes):
    """Retain source order with readable block and table-cell boundaries."""
    out = []
    for item in nodes:
        node = item["node"]
        if node["kind"] == "text":
            out.append(node["text"])
        elif node.get("content_kind") in {
            "paragraph",
            "heading",
            "list_item",
            "table",
            "table_row",
            "row",
        }:
            out.append("\n")
        elif node.get("content_kind") in {"table_cell", "cell"}:
            out.append(" | ")
    return "".join(out)


def project_blocks(library, publication_id, nodes):
    """Classify bounded nodes using retained table intervals, even mid-cell.

    XPath names are not reliable for namespace-qualified EPUBs. This read-only
    projection uses the already validated immutable model, without loading more
    text or reconstructing an unverified semantic grid.
    """
    from .book_model import connection

    blocks = []
    with connection(library.model(publication_id).path) as db:
        for item in nodes:
            node = item["node"]
            table = db.execute(
                "select 1 from nodes n join nodes t on t.document_id=n.document_id "
                "where n.id=? and t.content_kind='table' "
                "and t.preorder<=n.preorder and t.subtree_end>=n.preorder limit 1",
                (node["id"],),
            ).fetchone()
            kind = "table" if table else "text"
            text = project_text([item])
            if blocks and blocks[-1]["kind"] == kind:
                blocks[-1]["text"] += text
            else:
                blocks.append({"kind": kind, "text": text})
    return blocks
