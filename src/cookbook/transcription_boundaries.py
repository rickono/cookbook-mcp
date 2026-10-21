"""Conservative, opt-in semantic proposals over immutable scan evidence.

This module opens no files, invokes no models, and grants no approval. Geometry
and recognized headings are evidence for proposals, not authored truth.
"""

from __future__ import annotations

import re
from collections import Counter

from cookbook.transcription import snapshot_digest, validate_snapshot

VERSION = "scanned-boundaries.v1"
_HEADINGS = {"title", "section_header", "heading"}
_PARTS = {"ingredients", "instructions", "method", "preparation", "directions"}
_NONRECIPE = {"menu", "passage", "reference_entry", "reference"}
_ISOLATED = {"picture", "caption", "page_header", "page_footer"}
_STEP = re.compile(r"^\s*(\d+)[.)]\s+[A-Za-z]")
_QUANTITY = re.compile(r"^\s*(?:\d+(?:[./]\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])\s+\S")


def _rectangle(points):
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _same_lane(a, b, width):
    """Require left alignment or substantial overlap of both region widths."""
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    return abs(a[0] - b[0]) <= width * 0.08 or overlap >= 0.6 * max(
        a[2] - a[0], b[2] - b[0]
    )


def _under_heading(a, b, width):
    # A visibly page-spanning heading can enclose two columns. Narrow headings
    # cannot collect another column without additional source evidence.
    spanning = a[2] - a[0] >= width * 0.7 and a[0] <= b[0] and b[2] <= a[2]
    return spanning or _same_lane(a, b, width)


def _views(snapshot):
    lines = {line["id"]: line for page in snapshot["pages"] for line in page["lines"]}
    rank = {line_id: n for n, line_id in enumerate(lines)}
    blocks = snapshot["blocks"]
    # Parent/child evidence may overlap. The smallest direct region wins; equal
    # competing leaf regions stay ambiguous instead of claiming two owners.
    candidates = {line_id: [] for line_id in lines}
    for block in blocks:
        for line_id in block["line_ids"]:
            candidates[line_id].append(block)
    chosen = {}
    ambiguous = []
    for line_id, choices in candidates.items():
        leaves = [b for b in choices if not b["children"]] or choices
        size = min(len(b["line_ids"]) for b in leaves)
        best = [b for b in leaves if len(b["line_ids"]) == size]
        if len(best) == 1:
            chosen[line_id] = best[0]["id"]
        else:
            ambiguous.append(line_id)
    views = []
    for block in blocks:
        ids = sorted(
            (i for i in block["line_ids"] if chosen.get(i) == block["id"]),
            key=rank.__getitem__,
        )
        if not ids:
            continue
        points = [p for i in ids for p in lines[i]["polygon"]]
        views.append(
            {
                "block": block,
                "ids": ids,
                "box": _rectangle(points),
                "text": "\n".join(lines[i]["text"] for i in ids),
            }
        )
    isolated = [i for v in views if v["block"]["kind"] in _ISOLATED for i in v["ids"]]
    views = [v for v in views if v["block"]["kind"] not in _ISOLATED]
    ambiguous.extend(isolated)
    return lines, rank, views, ambiguous


def _steps(view, lines):
    marker = view["block"]["marker"]
    result = []
    for n, line_id in enumerate(view["ids"]):
        text = lines[line_id]["text"]
        match = _STEP.match(text)
        if not match and n == 0 and marker:
            match = _STEP.match(f"{marker} {text}")
        if match:
            result.append(int(match[1]))
    return result


def _classify(group, lines):
    labels = {v["block"]["kind"] for v in group["views"]}
    text_lines = [lines[i]["text"] for v in group["views"] for i in v["ids"]]
    quantities = sum(
        bool(_QUANTITY.match(t) and not _STEP.match(t)) for t in text_lines
    )
    steps = [n for v in group["views"] for n in _steps(v, lines)]
    if labels & {"reference_entry", "reference"}:
        return (
            "reference_entry",
            "candidate",
            ["Explicit reference-region label; ownership remains a proposal."],
        )
    if labels & {"menu", "passage"}:
        return (
            "passage",
            "candidate",
            ["Explicit nonrecipe-region label blocks recipe classification."],
        )
    headings = [
        v["text"].strip().lower()
        for v in group["views"]
        if v["block"]["kind"] in _HEADINGS
    ]
    if any(h in {"menu", "shopping list", "meal plan"} for h in headings):
        return (
            "passage",
            "candidate",
            ["Authored menu/shopping heading blocks recipe classification."],
        )
    if group["headed"] and quantities >= 2 and steps and steps[0] == 1:
        return (
            "recipe",
            "candidate",
            [
                "Independent heading with at least two quantity-led ingredients and numbered instructions starting at 1.",
                "Geometry proposes one region; no source review or completeness is asserted.",
            ],
        )
    body = [v for v in group["views"] if v["block"]["kind"] not in _HEADINGS]
    if group["headed"] and body and not quantities and not steps:
        return (
            "unclassified",
            "unresolved",
            [
                "Heading and prose may be a passage or detached recipe headnote; missing ingredient/method cues cannot determine type. Yield words alone are insufficient."
            ],
        )
    return (
        "unclassified",
        "unresolved",
        [
            "Recipe ownership/type is insufficiently evidenced; title-only, edge and partial content remain unresolved."
        ],
    )


def propose_boundaries(snapshot: dict) -> dict:
    """Return digest-bound selections; every recognized line has one owner.

    Recipe proposals need independent layout headings, quantity-led ingredients,
    and numbered instructions. Only an exact next step can continue a recipe on
    the immediately following physical page in a compatible layout lane.
    """
    validate_snapshot(snapshot)
    lines, rank, views, ambiguous = _views(snapshot)
    page_by_id = {p["id"]: p for p in snapshot["pages"]}
    groups = []
    links = []
    for page in sorted(snapshot["pages"], key=lambda p: p["physical_page"]):
        local = [v for v in views if v["block"]["page_id"] == page["id"]]
        local.sort(key=lambda v: (v["box"][1], v["box"][0], rank[v["ids"][0]]))
        headed = []
        orphan_views = []
        for view in local:
            label = view["block"]["kind"]
            heading = label in _HEADINGS and view["text"].strip().lower() not in _PARTS
            if heading or label in _NONRECIPE:
                # Consecutive aligned heading fragments can form a multi-line
                # title, at any vertical position and with a single word.
                previous = headed[-1] if headed else None
                if (
                    heading
                    and previous
                    and all(v["block"]["kind"] in _HEADINGS for v in previous["views"])
                    and _same_lane(previous["box"], view["box"], page["render_size"][0])
                    and 0
                    <= view["box"][1] - previous["box"][3]
                    <= 1.5 * (view["box"][3] - view["box"][1])
                ):
                    previous["views"].append(view)
                    previous["box"] = _rectangle(
                        [
                            [previous["box"][0], previous["box"][1]],
                            [view["box"][2], view["box"][3]],
                        ]
                    )
                else:
                    group = {
                        "views": [view],
                        "headed": heading,
                        "box": view["box"],
                        "page_id": page["id"],
                    }
                    headed.append(group)
                    groups.append(group)
                continue
            possible = [
                g
                for g in headed
                if g["box"][1] <= view["box"][1]
                and _under_heading(g["box"], view["box"], page["render_size"][0])
            ]
            if possible:
                closest_y = max(g["box"][1] for g in possible)
                closest = [g for g in possible if g["box"][1] == closest_y]
                if len(closest) == 1:
                    closest[0]["views"].append(view)
                    continue
            orphan_views.append(view)
        # Separate compatible lanes instead of combining an entire headingless
        # page. Ambiguous overlaps and unrelated prose never carry forward.
        orphans = []
        for view in orphan_views:
            compatible = [
                g
                for g in orphans
                if _same_lane(g["box"], view["box"], page["render_size"][0])
            ]
            if len(compatible) == 1:
                compatible[0]["views"].append(view)
            else:
                orphans.append(
                    {
                        "views": [view],
                        "headed": False,
                        "box": view["box"],
                        "page_id": page["id"],
                    }
                )
        for orphan in orphans:
            step_numbers = [n for v in orphan["views"] for n in _steps(v, lines)]
            # A detached sentence cannot borrow another region's later number.
            first_numbers = _steps(orphan["views"][0], lines)
            numbered_only = all(_steps(v, lines) for v in orphan["views"])
            previous = []
            if (
                first_numbers
                and numbered_only
                and step_numbers == sorted(set(step_numbers))
            ):
                for group in groups:
                    kind, _, _ = _classify(group, lines)
                    last_page = page_by_id[group["page_id"]]
                    old_numbers = [n for v in group["views"] for n in _steps(v, lines)]
                    method_views = [v for v in group["views"] if _steps(v, lines)]
                    if (
                        kind == "recipe"
                        and old_numbers
                        and last_page["physical_page"] + 1 == page["physical_page"]
                        and first_numbers[0] == old_numbers[-1] + 1
                        and _same_lane(
                            method_views[-1]["box"],
                            orphan["box"],
                            page["render_size"][0],
                        )
                        and last_page["render_size"] == page["render_size"]
                    ):
                        previous.append(group)
            if len(previous) == 1:
                owner = previous[0]
                links.append(
                    {
                        "group": owner,
                        "from_page_id": owner["page_id"],
                        "to_page_id": page["id"],
                        "line_ids": [i for v in orphan["views"] for i in v["ids"]],
                    }
                )
                owner["views"].extend(orphan["views"])
                owner["page_id"] = page["id"]
                owner["box"] = orphan["box"]
            else:
                groups.append(orphan)
    for line_id in ambiguous:
        groups.append(
            {
                "views": [
                    {
                        "ids": [line_id],
                        "block": {"kind": "unclassified", "marker": None},
                    }
                ],
                "headed": False,
            }
        )
    groups.sort(key=lambda g: min(rank[i] for v in g["views"] for i in v["ids"]))
    selections = []
    for n, group in enumerate(groups):
        kind, state, reasons = _classify(group, lines)
        group["id"] = f"boundary-{n + 1}"
        selections.append(
            {
                "id": group["id"],
                "kind": kind,
                "state": state,
                "reasons": reasons,
                "line_ids": sorted(
                    (i for v in group["views"] for i in v["ids"]), key=rank.__getitem__
                ),
            }
        )
    result = {
        "version": VERSION,
        "snapshot_digest": snapshot_digest(snapshot),
        "selections": selections,
        "links": [
            {
                "kind": "continuation",
                "selection_id": link["group"]["id"],
                "from_page_id": link["from_page_id"],
                "to_page_id": link["to_page_id"],
                "line_ids": sorted(link["line_ids"], key=rank.__getitem__),
                "state": "candidate",
                "reasons": [
                    "Exact next numbered instruction in a compatible lane on the immediately following physical page."
                ],
            }
            for link in links
        ],
        "unresolved_elements": [
            {
                "block_id": b["id"],
                "reasons": [
                    "Picture ownership is unresolved; proximity and appearance do not establish authorship."
                ],
            }
            for b in snapshot["blocks"]
            if b["kind"] == "picture"
        ],
    }
    validate_boundaries(snapshot, result)
    return result


def validate_boundaries(snapshot: dict, proposals: dict) -> None:
    """Reject stale, overlapping, missing or foreign evidence selections."""
    validate_snapshot(snapshot)
    if not isinstance(proposals, dict) or set(proposals) != {
        "version",
        "snapshot_digest",
        "selections",
        "links",
        "unresolved_elements",
    }:
        raise ValueError("Unexpected boundary proposal shape")
    if proposals["version"] != VERSION or proposals[
        "snapshot_digest"
    ] != snapshot_digest(snapshot):
        raise ValueError("Wrong boundary version or snapshot digest")
    lines = {line["id"]: page for page in snapshot["pages"] for line in page["lines"]}
    rank = {line_id: n for n, line_id in enumerate(lines)}
    selections = {}
    owned = []
    if any(
        not isinstance(proposals[key], list)
        for key in ("selections", "links", "unresolved_elements")
    ):
        raise ValueError("Proposal collections must be lists")
    for selection in proposals["selections"]:
        if not isinstance(selection, dict) or set(selection) != {
            "id",
            "kind",
            "line_ids",
            "state",
            "reasons",
        }:
            raise ValueError("Unexpected semantic selection shape")
        if (
            not isinstance(selection["id"], str)
            or not selection["id"]
            or selection["id"] in selections
        ):
            raise ValueError("Selection IDs must be unique nonempty strings")
        if (
            not isinstance(selection["kind"], str)
            or not isinstance(selection["state"], str)
            or selection["kind"]
            not in {
                "recipe",
                "passage",
                "reference_entry",
                "unclassified",
            }
            or selection["state"] not in {"candidate", "unresolved"}
        ):
            raise ValueError("Invalid semantic kind/state")
        _reasons(selection["reasons"])
        ids = selection["line_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(i, str) or i not in lines for i in ids)
        ):
            raise ValueError("Selections need existing evidence lines")
        if ids != sorted(set(ids), key=rank.__getitem__):
            raise ValueError("Selection lines must be unique and in canonical order")
        selections[selection["id"]] = selection
        owned.extend(ids)
    if Counter(owned) != Counter(list(lines)):
        raise ValueError("Every canonical line must have exactly one selection owner")
    pages = {p["id"]: p for p in snapshot["pages"]}
    for link in proposals["links"]:
        if not isinstance(link, dict) or set(link) != {
            "kind",
            "selection_id",
            "from_page_id",
            "to_page_id",
            "line_ids",
            "state",
            "reasons",
        }:
            raise ValueError("Unexpected continuation link shape")
        _reasons(link["reasons"])
        if any(
            not isinstance(link[key], str)
            for key in ("kind", "state", "selection_id", "from_page_id", "to_page_id")
        ):
            raise ValueError("Continuation identifiers must be strings")
        source, target = pages.get(link["from_page_id"]), pages.get(link["to_page_id"])
        selection = selections.get(link["selection_id"])
        if (
            link["kind"] != "continuation"
            or link["state"] != "candidate"
            or not source
            or not target
            or not selection
            or selection["kind"] != "recipe"
            or target["physical_page"] != source["physical_page"] + 1
        ):
            raise ValueError("Invalid continuation endpoints/type")
        ids = link["line_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(
                not isinstance(i, str)
                or i not in selection["line_ids"]
                or lines[i]["id"] != target["id"]
                for i in ids
            )
        ):
            raise ValueError(
                "Continuation evidence must belong to the target page/selection"
            )
        if ids != sorted(set(ids), key=rank.__getitem__) or not any(
            lines[i]["id"] == source["id"] for i in selection["line_ids"]
        ):
            raise ValueError(
                "Continuation needs ordered evidence and a source-page selection"
            )
    blocks = {b["id"]: b for b in snapshot["blocks"]}
    seen = set()
    for element in proposals["unresolved_elements"]:
        if not isinstance(element, dict) or set(element) != {"block_id", "reasons"}:
            raise ValueError("Unexpected unresolved element shape")
        _reasons(element["reasons"])
        block_id = element["block_id"]
        if (
            not isinstance(block_id, str)
            or block_id not in blocks
            or block_id in seen
            or blocks[block_id]["kind"] != "picture"
        ):
            raise ValueError("Unresolved picture IDs must resolve uniquely")
        seen.add(block_id)
    if seen != {b["id"] for b in snapshot["blocks"] if b["kind"] == "picture"}:
        raise ValueError("All picture ownership must remain unresolved")


def _reasons(reasons):
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(r, str) or not r.strip() for r in reasons)
    ):
        raise ValueError("Proposal reasons must be nonempty strings")
