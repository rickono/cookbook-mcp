"""Small server-rendered, loopback-only dashboard. No file or content serving routes."""

import html
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.routing import Route

from ..usage import aggregate


def esc(value):
    return html.escape(str(value), quote=True)


def stamp(value):
    if value is None:
        return "never observed"
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(value), UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def badge(value):
    return f'<span class="badge">{esc(value)}</span>'


def layout(title, body):
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Cookbook library</title><link rel="stylesheet" href="/style.css"><script src="/dashboard.js" defer></script></head><body><header><a class="brand" href="/">Cookbook library</a><nav aria-label="Main"><a href="/">Inventory</a><a href="/analytics">Retrieval activity</a><a href="/observations">Observations</a></nav><form method="post" action="/refresh"><button>Refresh observations</button></form></header><main>{body}</main><footer>Local, read-only observations · Coverage, review, publication and access are independent.</footer></body></html>"""
    )


def source_health(snapshot):
    failures = sum(o["status"] != "ok" or o["stale"] for o in snapshot["observations"])
    return (
        f'<p class="muted" role="status">{failures} unknown or stale observation sources · {"refresh in progress" if snapshot["refreshing"] else "automatic refresh enabled"} · Snapshot {esc(stamp(snapshot["at"]))}</p>'
        + (
            f'<p class="warning">{esc(snapshot["storage_error"])}</p>'
            if snapshot["storage_error"]
            else ""
        )
    )


def state_text(book, dimension):
    state = book["states"][dimension]
    previous = book.get("previous_states", {}).get(dimension, [])
    if state == "unknown" and previous:
        return "unknown; previous evidence: " + "; ".join(previous)
    return state


def coverage_text(book):
    if not book["coverage"]:
        return "unknown"
    parts = []
    for r in book["coverage"]:
        c = r["coverage"]
        total = c["total"] if c["total"] is not None else "unknown total"
        text = f"{c['transcribed']} transcribed / {total} pages; {c['blank']} blank, {c['failed']} failed, {c['unaccounted'] if c['unaccounted'] is not None else 'unknown'} unaccounted"
        parts.append(text + (" (previous evidence)" if not r["current"] else ""))
    return "; ".join(parts)


def detail_block(title, rows):
    if not rows:
        return f'<section><h2>{esc(title)}</h2><p class="muted">No observed evidence. This does not establish an empty backlog or cleared state.</p></section>'
    rendered = []
    for row in rows:
        rendered.append(
            "<dl>"
            + "".join(
                f"<dt>{esc(k.replace('_', ' '))}</dt><dd>{esc(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else stamp(v) if k in {'observed_at', 'at'} and isinstance(v, (float, int)) else v)}</dd>"
                for k, v in row.items()
            )
            + "</dl>"
        )
    return f"<section><h2>{esc(title)}</h2>{''.join(rendered)}</section>"


def reader_entry(dashboard, book):
    """Link only current observed catalog membership, never processing metadata."""
    from ..reader_content import decode_location, reading_link

    origin = dashboard.config.get("reader_origin")
    if not origin:
        return ""
    for fact in book["facts"]:
        if (
            fact["dimension"] == "publication"
            and fact["state"] == "catalog present"
            and fact["current"]
        ):
            try:
                citation = {
                    "publication_id": fact["publication"],
                    "book_id": fact["book_id"],
                    "source_id": fact["source_id"],
                }
                link = reading_link(citation)
                from urllib.parse import parse_qs

                decode_location(parse_qs(urlsplit(link).query)["at"][0])
            except (KeyError, TypeError, ValueError):
                continue
            return '<a href="' + esc(origin + link) + '">Open in library reader</a>'
    return ""


def create_app(dashboard):
    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=dashboard.run, daemon=True)
        thread.start()
        yield
        dashboard.stop.set()
        thread.join(timeout=1)

    async def inventory(request):
        snap = dashboard.snapshot()
        q = request.query_params.get("q", "")[:200]
        membership = request.query_params.get("membership", "included")
        attention = request.query_params.get("attention") == "yes"
        books = [
            b
            for b in snap["books"]
            if (membership == "all" or b["membership"] == membership)
            and (not attention or b["attention"])
            and q.casefold()
            in (b["title"] + " " + b["id"] + " " + json.dumps(b["aliases"])).casefold()
        ]
        s = snap["summary"]
        body = '<div class="intro"><p class="eyebrow">Your collection</p><h1>Every book, in view.</h1><p>Find what is available, what is missing, and what needs attention.</p></div>'
        body += (
            '<div class="summary">'
            + "".join(
                f"<div><strong>{s[k]}</strong><span>{label}</span></div>"
                for k, label in [
                    ("included", "intended editions"),
                    ("held", "with holds"),
                    ("attention", "need attention"),
                    ("undecided", "undecided"),
                    ("conflict", "membership conflicts"),
                ]
            )
            + '</div><p class="muted">Attention and hold counts overlap. Each included edition counts once per dimension.</p>'
        )
        body += source_health(snap)
        options = "".join(
            f'<option value="{m}" {"selected" if m == membership else ""}>{m.title()}</option>'
            for m in ["included", "undecided", "conflict", "excluded", "all"]
        )
        body += f'<form class="filters" method="get"><label>Search books<input name="q" value="{esc(q)}" type="search" placeholder="Title or namespaced record"></label><label>Membership<select name="membership">{options}</select></label><label class="check"><input type="checkbox" name="attention" value="yes" {"checked" if attention else ""}> Needs attention</label><button>Apply filters</button></form>'
        body += f'<p>{len(books)} editions shown</p><div class="table-wrap"><table><caption class="sr-only">Book inventory with independent states</caption><thead><tr><th>Book edition</th><th>Processing</th><th>Declared coverage</th><th>Review</th><th>Publication</th><th>Current access</th></tr></thead><tbody>'
        for b in books:
            link = "/book?" + urlencode({"id": b["id"]})
            body += f'<tr><td><a class="book-title" href="{esc(link)}">{esc(b["title"])}</a><small>{esc(b["membership"])} · {len(b["aliases"])} records{" · provisional identity" if b["provisional"] else ""}</small>{badge("held") if b["holds"] else ""}{reader_entry(dashboard, b)}</td><td>{esc(state_text(b, "processing"))}</td><td>{esc(coverage_text(b))}</td><td>{esc(state_text(b, "review"))}</td><td>{esc(state_text(b, "publication"))}</td><td>{esc(state_text(b, "access"))}</td></tr>'
        body += "</tbody></table></div>"
        if not books:
            body += '<p class="empty">No matching editions. Configure the private intended-book registry or change filters. Missing observations never establish exclusion.</p>'
        return layout("Inventory", body)

    async def book(request):
        snap = dashboard.snapshot()
        b = next(
            (b for b in snap["books"] if b["id"] == request.query_params.get("id")),
            None,
        )
        if b is None:
            return PlainTextResponse("Unknown edition", status_code=404)
        body = f'<a href="/">← Inventory</a><h1>{esc(b["title"])}</h1><p class="identifier">{esc(b["id"])}</p>{badge(b["membership"])}'
        body += source_health(snap)
        body += reader_entry(dashboard, b)
        body += (
            '<div class="states">'
            + "".join(
                f"<div><h2>{esc(k.title())}</h2><p>{esc(v)}</p></div>"
                for k, v in b["states"].items()
            )
            + "</div>"
        )
        body += f"<p>Declared coverage: {esc(coverage_text(b))}. Metadata-only inspection does not validate the transcription.</p><p>Owner queue total: {snap['owner_queue_total'] if snap['owner_queue_total'] is not None else 'unknown; known items shown below'}.</p>"
        for title, key in [
            ("Aliases and source records", "aliases"),
            ("Membership evidence", "claims"),
            ("Book holds", "holds"),
            ("Current blockers", "blockers"),
            ("Owner queue", "queue"),
            ("Local candidates and published coverage", "coverage"),
            ("Scoped state evidence", "facts"),
            ("Correction stages", "corrections"),
            ("Worker observations", "heartbeats"),
            ("Attempt history", "history"),
        ]:
            body += detail_block(title, b[key])
        return layout(b["title"], body)

    async def observations(request):
        snap = dashboard.snapshot()
        body = (
            "<h1>Observation health</h1><p>Failures leave current state unknown. Previous evidence retains its observation date.</p>"
            + source_health(snap)
        )
        body += detail_block(
            "Configured sources",
            [{k: v for k, v in o.items() if k != "data"} for o in snap["observations"]],
        )
        return layout("Observations", body)

    def analytics_data(request):
        try:
            days = int(request.query_params.get("days", "7"))
        except ValueError:
            days = 7
        if days not in (1, 7, 30, 0):
            days = 7
        return aggregate(
            dashboard.config.get("usage", []),
            days=days,
            publication=request.query_params.get("publication") or None,
            now=dashboard.clock(),
        )

    async def analytics(request):
        import asyncio

        data = await asyncio.to_thread(analytics_data, request)
        options = "".join(
            f'<option value="{d}" {"selected" if data["window_days"] == d else ""}>{label}</option>'
            for d, label in [
                (1, "24 hours"),
                (7, "7 days"),
                (30, "30 days"),
                (0, "All retained history"),
            ]
        )
        body = f'<h1>Retrieval activity</h1><p>Tool activity does not establish human readership or cooking.</p><p class="notice">{esc(data["status"])}</p><form class="filters"><label>UTC window<select name="days">{options}</select></label><label>Publication<input name="publication" value="{esc(data["publication"] or "")}" placeholder="All publications"></label><button>Apply</button></form>'
        body += detail_block("Collection coverage", data["collectors"])
        body += "".join(f'<p class="warning">{esc(e)}</p>' for e in data["errors"])
        if data["collectors"]:
            body += '<h2>Daily activity · UTC</h2><div class="chart" role="img" aria-label="Daily recorded retrieval events">'
            maximum = max(data["daily"].values(), default=1)
            for day, count in sorted(data["daily"].items()):
                body += f'<div class="bar-row"><span>{esc(day)}</span><meter min="0" max="{maximum}" value="{count}">{count}</meter><strong>{count}</strong></div>'
            body += f"</div><p>{data['unique_content_scopes']} distinct successful content scopes in this window. Continuations and repeated invocations remain separate calls.</p>"
            body += detail_block(
                "Recorded totals",
                [{"metric": k, "count": v} for k, v in sorted(data["totals"].items())],
            )
            body += detail_block(
                "Edition attribution",
                [
                    {"source": k, "counts": v}
                    for k, v in sorted(data["editions"].items())
                ],
            )
        return layout("Retrieval activity", body)

    async def snapshot(request):
        return JSONResponse(dashboard.snapshot())

    async def usage(request):
        import asyncio

        return JSONResponse(await asyncio.to_thread(analytics_data, request))

    async def refresh(request):
        dashboard.tick(force=True)
        return RedirectResponse("/", status_code=303)

    async def asset(request):
        name = request.path_params["name"]
        if name not in {"style.css", "dashboard.js"}:
            return PlainTextResponse("Not found", status_code=404)
        return PlainTextResponse(
            Path(__file__).with_name(name).read_text(),
            media_type="text/css" if name.endswith("css") else "text/javascript",
        )

    app = Starlette(
        routes=[
            Route("/", inventory),
            Route("/book", book),
            Route("/observations", observations),
            Route("/analytics", analytics),
            Route("/api/snapshot", snapshot),
            Route("/api/usage", usage),
            Route("/refresh", refresh, methods=["POST"]),
            Route("/{name}", asset),
        ],
        lifespan=lifespan,
    )

    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            _port = parsed.port  # validate malformed ports
            valid = (
                parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and not parsed.username
                and not parsed.password
            )
        except ValueError:
            valid = False
        client = request.client.host if request.client else "127.0.0.1"
        if not valid or client not in {"127.0.0.1", "::1", "testclient"}:
            return PlainTextResponse("Loopback access required", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != "http://" + host:
            return PlainTextResponse("Origin rejected", status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=local_only)
    return app
