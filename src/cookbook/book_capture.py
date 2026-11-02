"""Canonical EPUB source capture. No PDF, OCR, inference or network execution."""

# Local traversal closures are executed synchronously within their current book/document.
# ruff: noqa: B023
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree
from pydantic import TypeAdapter

from .book_types import (
    ContentNode,
    Edition,
    ElementNode,
    LinkTarget,
    NavigationEntry,
    ReadingOccurrence,
    Resource,
    SourceDocument,
    SourceLink,
    TextNode,
    UnresolvedContent,
)

NODES = TypeAdapter(ContentNode)


def key(*parts):
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:32]


def hashtext(t):
    return hashlib.sha256(t.encode()).hexdigest()


def hashfile(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def xml(raw):
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser)
    return root, [str(e) for e in parser.error_log]


def local(e):
    return (
        etree.QName(e).localname.lower() if isinstance(e.tag, str) else "#non-element"
    )


def plain(e):
    return re.sub(r"\s+", " ", "".join(e.itertext())).strip()


def hrefpath(base, href):
    u = urlsplit(href)
    if u.scheme or u.netloc:
        return None, unquote(u.fragment)
    p = (
        posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(u.path)))
        if u.path
        else base
    )
    if p == ".." or p.startswith(("/", "../")):
        return None, unquote(u.fragment)
    return p, unquote(u.fragment)


KIND = {
    "body": "document",
    "p": "paragraph",
    "ul": "list",
    "ol": "list",
    "dl": "list",
    "li": "list_item",
    "dt": "list_item",
    "dd": "list_item",
    "table": "table",
    "thead": "table_section",
    "tbody": "table_section",
    "tfoot": "table_section",
    "tr": "table_row",
    "td": "table_cell",
    "th": "table_cell",
    "figure": "figure",
    "img": "image",
    "image": "image",
    "figcaption": "caption",
    "caption": "caption",
    "aside": "aside",
    "blockquote": "quotation",
    "q": "quotation",
    "pre": "code",
    "code": "code",
    "br": "line_break",
    "a": "link",
    "em": "emphasis",
    "strong": "emphasis",
    "b": "emphasis",
    "i": "emphasis",
    "sup": "emphasis",
    "sub": "emphasis",
    "math": "math",
    "script": "non_reading",
    "style": "non_reading",
    "div": "container",
    "span": "container",
    "section": "container",
    "article": "container",
    "hr": "container",
    "svg": "container",
}


SCHEMA = "\n CREATE TABLE editions(id TEXT PRIMARY KEY,calibre_id INTEGER UNIQUE,title TEXT,payload TEXT);\n CREATE TABLE resources(id TEXT PRIMARY KEY,edition_id TEXT,path TEXT,media_type TEXT,role TEXT,payload TEXT, UNIQUE(edition_id,path));\n CREATE TABLE documents(id TEXT PRIMARY KEY,edition_id TEXT,path TEXT,root_id TEXT,payload TEXT, UNIQUE(edition_id,path));\n CREATE TABLE nodes(id TEXT PRIMARY KEY,document_id TEXT,parent_id TEXT,preorder INTEGER,subtree_end INTEGER,node_kind TEXT,content_kind TEXT,xpath TEXT,text TEXT,payload TEXT, UNIQUE(document_id,preorder));\n CREATE INDEX nodes_parent ON nodes(parent_id,preorder);\n CREATE INDEX nodes_xpath ON nodes(document_id,xpath);\n CREATE TABLE occurrences(id TEXT PRIMARY KEY,edition_id TEXT,document_id TEXT,ordinal INTEGER,payload TEXT, UNIQUE(edition_id,ordinal));\n CREATE TABLE links(id TEXT PRIMARY KEY,edition_id TEXT,document_id TEXT,node_id TEXT,target_document TEXT,target_node TEXT,state TEXT,payload TEXT);\n CREATE TABLE navigation(id TEXT PRIMARY KEY,edition_id TEXT,parent_id TEXT,kind TEXT,label TEXT,target_node TEXT,ordinal INTEGER,payload TEXT);\n CREATE TABLE spans(id TEXT PRIMARY KEY,edition_id TEXT,payload TEXT);\n CREATE TABLE entities(id TEXT PRIMARY KEY,edition_id TEXT,kind TEXT,label TEXT,payload TEXT);\n CREATE INDEX entities_kind ON entities(kind,edition_id);\n CREATE TABLE relations(id TEXT PRIMARY KEY,edition_id TEXT,relation TEXT,source_id TEXT,target_id TEXT,payload TEXT);\n CREATE TABLE issues(id TEXT PRIMARY KEY,edition_id TEXT,scope_id TEXT,code TEXT,payload TEXT);\n\n"


def create_db(path):
    if path.exists():
        raise ValueError("Whole-book output database must be new")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def capture(books, publication_id, path, progress=lambda event: None):
    db = create_db(path)
    try:
        summaries = []
        for b in books:
            bid = b["calibre_id"]
            path = Path(b["path"])
            if path.suffix.lower() != ".epub":
                raise ValueError("Whole-book native capture accepts EPUB only")
            sha = hashfile(path)
            if b["source_id"] != "epub:" + sha:
                raise ValueError("Original source checksum mismatch")
            edition = Edition(
                id=b["id"],
                publication_id=publication_id,
                title=b["title"],
                authors=json.loads(b["authors"]),
                source_id=b["source_id"],
                source_sha256=sha,
                format="EPUB",
                model_version="whole-book-draft-v1",
            )
            db.execute(
                "insert into editions values(?,?,?,?)",
                (edition.id, bid, edition.title, edition.model_dump_json()),
            )
            stats = {
                "book": bid,
                "title": edition.title,
                "source_sha256": sha,
                "resources": 0,
                "documents": 0,
                "reading_occurrences": 0,
                "nodes": 0,
                "text_nodes": 0,
                "native_characters": 0,
                "images": 0,
                "inline_images": 0,
                "tables": 0,
                "table_cells": 0,
                "spanning_cells": 0,
                "lists": 0,
                "links": 0,
                "navigation_entries": 0,
                "parser_diagnostics": 0,
                "image_only_spine_documents": 0,
                "native_body_text_roundtrip": True,
            }
            resources = {}
            documents = {}
            nodepaths = {}
            anchors = {}
            pendinglinks = []
            navraw = []
            spine = []
            imageonly = set()
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if (
                    len(names) != len(set(names))
                    or sum(i.file_size for i in z.infolist()) > 4_000_000_000
                ):
                    raise ValueError("Duplicate or oversized EPUB archive")

                def read(name):
                    if z.getinfo(name).file_size > 32_000_000:
                        raise ValueError("Bounded XML member required")
                    return z.read(name)

                container, _ = xml(read("META-INF/container.xml"))
                opf = container.xpath('//*[local-name()="rootfile"]')[0].get(
                    "full-path"
                )
                package, _ = xml(read(opf))
                manifest = {
                    e.get("id"): e
                    for e in package.xpath('//*[local-name()="manifest"]/*')
                }
                mime = {}
                props = {}
                for item in manifest.values():
                    rp, _ = hrefpath(opf, item.get("href", ""))
                    if rp:
                        mime[rp] = item.get("media-type")
                        props[rp] = item.get("properties", "")
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    mt = mime.get(info.filename)
                    role = (
                        "navigation"
                        if "nav" in props.get(info.filename, "").split()
                        or mt == "application/x-dtbncx+xml"
                        else "document"
                        if mt in ("application/xhtml+xml", "text/html")
                        or info.filename.endswith((".xhtml", ".html", ".htm"))
                        else "image"
                        if mt and mt.startswith("image/")
                        else "style"
                        if mt == "text/css"
                        else "font"
                        if mt
                        and (
                            "font" in mt or mt.startswith("application/vnd.ms-opentype")
                        )
                        else "package"
                        if info.filename == opf or info.filename.startswith("META-INF/")
                        else "other"
                    )
                    r = Resource(
                        id=key(sha, info.filename, "resource"),
                        edition_id=edition.id,
                        path=info.filename,
                        media_type=mt,
                        byte_size=info.file_size,
                        role=role,
                        zip_crc32=info.CRC,
                    )
                    resources[info.filename] = r
                    db.execute(
                        "insert into resources values(?,?,?,?,?,?)",
                        (
                            r.id,
                            edition.id,
                            r.path,
                            r.media_type,
                            r.role,
                            r.model_dump_json(),
                        ),
                    )
                stats["resources"] = len(resources)
                for si, itemref in enumerate(
                    package.xpath('//*[local-name()="spine"]/*')
                ):
                    item = manifest[itemref.get("idref")]
                    rp, _ = hrefpath(opf, item.get("href", ""))
                    spine.append((si, rp, itemref.get("linear", "yes") != "no"))
                docpaths = [
                    p
                    for p, r in resources.items()
                    if r.role in ("document", "navigation")
                    and (
                        mime.get(p) in ("application/xhtml+xml", "text/html")
                        or p.endswith((".xhtml", ".html", ".htm"))
                    )
                ]
                for docpath in docpaths:
                    root, errors = xml(read(docpath))
                    if root is None:
                        raise ValueError("EPUB document has no parsed root")
                    bodies = root.xpath('//*[local-name()="body"]')
                    body = bodies[0] if bodies else root
                    docid = key(sha, docpath, "document")
                    nodes = []
                    docanchors = {}
                    order = 0
                    reconstructed = []
                    kindcounts = {}
                    docimages = 0

                    def add_text(text, owner, parent, ordinal, slot):
                        nonlocal order
                        n = TextNode(
                            kind="text",
                            id=key(sha, docpath, owner, slot, "source-dom-v1"),
                            document_id=docid,
                            parent_id=parent,
                            child_ordinal=ordinal,
                            preorder=order,
                            source_xpath=owner,
                            source_slot=slot,
                            text=text,
                        )
                        order += 1
                        nodes.append(n)
                        reconstructed.append(text)
                        return n.id

                    def walk(e, parent=None, ordinal=0):
                        nonlocal order, docimages
                        xp = e.getroottree().getpath(e)
                        tag = local(e)
                        nid = key(sha, docpath, xp, "element", "source-dom-v1")
                        pre = order
                        order += 1
                        ck = (
                            "heading"
                            if re.fullmatch("h[1-6]", tag)
                            else KIND.get(tag, "unclassified")
                        )
                        attrs = dict(e.attrib) if isinstance(e.tag, str) else {}
                        if e.get("id"):
                            docanchors[e.get("id")] = nid
                        if tag == "a" and e.get("name"):
                            docanchors[e.get("name")] = nid
                        childids = []
                        # Comments/processing-instructions remain traceable elements but are not prose.
                        if isinstance(e.tag, str) and e.text is not None:
                            childids.append(
                                add_text(e.text, xp, nid, len(childids), "text")
                            )
                        for child in e:
                            childids.append(walk(child, nid, len(childids)))
                            if child.tail is not None:
                                childids.append(
                                    add_text(
                                        child.tail,
                                        child.getroottree().getpath(child),
                                        nid,
                                        len(childids),
                                        "tail",
                                    )
                                )
                        kwargs = {}
                        if ck == "heading":
                            kwargs["heading_level"] = int(tag[1])
                        if ck == "list":
                            kwargs["list_kind"] = {
                                "ul": "unordered",
                                "ol": "ordered",
                                "dl": "definition",
                            }[tag]
                        if ck == "table_cell":
                            for attr, field in [
                                ("rowspan", "table_row_span"),
                                ("colspan", "table_column_span"),
                            ]:
                                val = e.get(attr)
                                if val and val.isdigit() and int(val) > 0:
                                    kwargs[field] = int(val)
                                elif val:
                                    errors.append(
                                        "Unresolved " + attr + " value at " + xp
                                    )
                        href = (
                            e.get("src")
                            if tag == "img"
                            else e.get("href")
                            or e.get("{http://www.w3.org/1999/xlink}href")
                            if tag == "image"
                            else None
                        )
                        if ck == "image":
                            docimages += 1
                            rp, _ = hrefpath(docpath, href or "")
                            if href and rp in resources:
                                kwargs["asset_resource_id"] = resources[rp].id
                            kwargs["alt_text"] = e.get("alt")
                            if any(local(a) == "p" for a in e.iterancestors()):
                                stats["inline_images"] += 1
                        n = ElementNode(
                            kind="element",
                            id=nid,
                            document_id=docid,
                            parent_id=parent,
                            child_ordinal=ordinal,
                            preorder=pre,
                            subtree_end=order - 1,
                            source_xpath=xp,
                            source_tag=e.tag
                            if isinstance(e.tag, str)
                            else "#non-element",
                            content_kind=ck,
                            source_attributes=attrs,
                            child_ids=childids,
                            **kwargs,
                        )
                        nodes.append(n)
                        nodepaths[(docpath, xp)] = nid
                        kindcounts[ck] = kindcounts.get(ck, 0) + 1
                        linkhref = e.get("href") if tag == "a" else href
                        if linkhref:
                            pendinglinks.append(
                                (
                                    docpath,
                                    nid,
                                    "hyperlink" if tag == "a" else "image_source",
                                    linkhref,
                                )
                            )
                        return nid

                    rootid = walk(body)
                    expected = "".join(body.itertext())
                    actual = "".join(reconstructed)
                    if expected != actual:
                        raise RuntimeError(
                            "Native body text round-trip failed: " + docpath
                        )
                    nodes.sort(key=lambda n: n.preorder)
                    for n in nodes:
                        NODES.validate_python(n)
                        end = (
                            n.subtree_end if isinstance(n, ElementNode) else n.preorder
                        )
                        db.execute(
                            "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
                            (
                                n.id,
                                docid,
                                n.parent_id,
                                n.preorder,
                                end,
                                n.kind,
                                n.content_kind
                                if isinstance(n, ElementNode)
                                else "text",
                                n.source_xpath,
                                n.text if isinstance(n, TextNode) else None,
                                n.model_dump_json(),
                            ),
                        )
                    doc = SourceDocument(
                        id=docid,
                        edition_id=edition.id,
                        resource_id=resources[docpath].id,
                        path=docpath,
                        root_node_id=rootid,
                        body_text_sha256=hashtext(expected),
                        parser_diagnostics=errors,
                    )
                    documents[docpath] = doc
                    anchors[docpath] = docanchors
                    db.execute(
                        "insert into documents values(?,?,?,?,?)",
                        (doc.id, edition.id, docpath, rootid, doc.model_dump_json()),
                    )
                    stats["documents"] += 1
                    stats["nodes"] += len(nodes)
                    stats["text_nodes"] += sum(isinstance(n, TextNode) for n in nodes)
                    stats["native_characters"] += len(expected)
                    stats["images"] += docimages
                    stats["tables"] += kindcounts.get("table", 0)
                    stats["table_cells"] += kindcounts.get("table_cell", 0)
                    stats["lists"] += kindcounts.get("list", 0)
                    stats["spanning_cells"] += sum(
                        isinstance(n, ElementNode)
                        and (
                            (n.table_row_span or 1) > 1
                            or (n.table_column_span or 1) > 1
                        )
                        for n in nodes
                    )
                    stats["parser_diagnostics"] += len(errors)
                    if not expected.strip() and docimages:
                        imageonly.add(docpath)
                    for k, error in enumerate(errors):
                        issue = UnresolvedContent(
                            id=key(docid, "parse", k),
                            edition_id=edition.id,
                            scope_id=docid,
                            code="parser_diagnostic",
                            explanation=error,
                            evidence_span_ids=[],
                        )
                        db.execute(
                            "insert into issues values(?,?,?,?,?)",
                            (
                                issue.id,
                                edition.id,
                                docid,
                                issue.code,
                                issue.model_dump_json(),
                            ),
                        )
                    # Capture EPUB navigation from its authored structure, not generated headings.
                    if "nav" in props.get(docpath, "").split():
                        for nav in root.xpath('//*[local-name()="nav"]'):
                            nt = nav.get("{http://www.idpf.org/2007/ops}type", "")
                            nk = (
                                "toc"
                                if "toc" in nt
                                else "landmark"
                                if "landmarks" in nt
                                else "page_list"
                                if "page-list" in nt
                                else "other"
                            )

                            def visit_nav(el, parent=None):
                                for child in el:
                                    np = parent
                                    if local(child) == "li":
                                        a = next(
                                            (
                                                a
                                                for a in child.iter()
                                                if local(a) == "a" and a.get("href")
                                            ),
                                            None,
                                        )
                                        labelnode = (
                                            a
                                            if a is not None
                                            else next(
                                                (
                                                    a
                                                    for a in child
                                                    if local(a) == "span"
                                                ),
                                                None,
                                            )
                                        )
                                        if labelnode is not None:
                                            navid = key(
                                                docid,
                                                child.getroottree().getpath(child),
                                                "navigation",
                                            )
                                            navraw.append(
                                                (
                                                    navid,
                                                    parent,
                                                    nk,
                                                    plain(labelnode),
                                                    resources[docpath].id,
                                                    child.getroottree().getpath(child),
                                                    docpath,
                                                    a.get("href")
                                                    if a is not None
                                                    else "",
                                                )
                                            )
                                            np = navid
                                    visit_nav(child, np)

                            visit_nav(nav)
                # NCX nodes have source hierarchy separate from XHTML documents.
                for rp, mt in mime.items():
                    if mt == "application/x-dtbncx+xml":
                        nr, errors = xml(read(rp))
                        for el in nr.xpath('//*[local-name()="navPoint"]'):
                            parent = next(
                                (
                                    a
                                    for a in el.iterancestors()
                                    if local(a) == "navpoint"
                                ),
                                None,
                            )
                            labels = el.xpath('./*[local-name()="navLabel"]')
                            targets = el.xpath('./*[local-name()="content"]')
                            navraw.append(
                                (
                                    key(
                                        sha,
                                        rp,
                                        el.getroottree().getpath(el),
                                        "navigation",
                                    ),
                                    key(
                                        sha,
                                        rp,
                                        parent.getroottree().getpath(parent),
                                        "navigation",
                                    )
                                    if parent is not None
                                    else None,
                                    "ncx",
                                    plain(labels[0]) if labels else "",
                                    resources[rp].id,
                                    el.getroottree().getpath(el),
                                    rp,
                                    targets[0].get("src", "") if targets else "",
                                )
                            )

                def resolve(base, href):
                    rp, an = hrefpath(base, href)
                    if rp is None:
                        return LinkTarget(
                            state="external",
                            resource_id=None,
                            document_id=None,
                            node_id=None,
                            uri=href,
                            reason="External or unsafe path retained; never fetched",
                        )
                    if rp not in resources:
                        return LinkTarget(
                            state="unresolved",
                            resource_id=None,
                            document_id=None,
                            node_id=None,
                            uri=href,
                            reason="Resource absent from original archive",
                        )
                    d = documents.get(rp)
                    nid = (
                        anchors.get(rp, {}).get(an)
                        if an
                        else d.root_node_id
                        if d
                        else None
                    )
                    if an and nid is None:
                        return LinkTarget(
                            state="unresolved",
                            resource_id=resources[rp].id,
                            document_id=d.id if d else None,
                            node_id=None,
                            uri=href,
                            reason="Anchor absent from modeled document",
                        )
                    return LinkTarget(
                        state="resolved_node" if nid else "resolved_resource",
                        resource_id=resources[rp].id,
                        document_id=d.id if d else None,
                        node_id=nid,
                        uri=href,
                        reason=None,
                    )

                for ordinal, rp, linear in spine:
                    if rp not in documents:
                        raise RuntimeError(
                            "Spine resource lacks captured document: " + str(rp)
                        )
                    o = ReadingOccurrence(
                        id=key(sha, "reading", ordinal),
                        edition_id=edition.id,
                        document_id=documents[rp].id,
                        ordinal=ordinal,
                        linear=linear,
                    )
                    db.execute(
                        "insert into occurrences values(?,?,?,?,?)",
                        (o.id, edition.id, o.document_id, ordinal, o.model_dump_json()),
                    )
                    stats["reading_occurrences"] += 1
                stats["unique_spine_documents"] = len({rp for _, rp, _ in spine})
                stats["image_only_spine_documents"] = len(
                    imageonly & {rp for _, rp, _ in spine}
                )
                for docpath, nid, kind, href in pendinglinks:
                    l = SourceLink(
                        id=key(nid, kind, href),
                        document_id=documents[docpath].id,
                        node_id=nid,
                        relation=kind,
                        target=resolve(docpath, href),
                    )
                    db.execute(
                        "insert into links values(?,?,?,?,?,?,?,?)",
                        (
                            l.id,
                            edition.id,
                            l.document_id,
                            nid,
                            l.target.document_id,
                            l.target.node_id,
                            l.target.state,
                            l.model_dump_json(),
                        ),
                    )
                    stats["links"] += 1
                    if l.target.state == "unresolved":
                        code = (
                            "unresolved_asset"
                            if kind == "image_source"
                            else "unresolved_link"
                        )
                        issue = UnresolvedContent(
                            id=key(l.id, "issue"),
                            edition_id=edition.id,
                            scope_id=l.id,
                            code=code,
                            explanation=l.target.reason or code,
                            evidence_span_ids=[],
                        )
                        db.execute(
                            "insert into issues values(?,?,?,?,?)",
                            (issue.id, edition.id, l.id, code, issue.model_dump_json()),
                        )
                for i, (nid, parent, nk, label, rid, xp, base, href) in enumerate(
                    navraw
                ):
                    n = NavigationEntry(
                        id=nid,
                        edition_id=edition.id,
                        parent_id=parent,
                        ordinal=i,
                        kind=nk,
                        label=label,
                        source_resource_id=rid,
                        source_xpath=xp,
                        target=resolve(base, href),
                    )
                    db.execute(
                        "insert into navigation values(?,?,?,?,?,?,?,?)",
                        (
                            n.id,
                            edition.id,
                            parent,
                            n.kind,
                            label,
                            n.target.node_id,
                            i,
                            n.model_dump_json(),
                        ),
                    )
                    stats["navigation_entries"] += 1
            # No changed source or cached snapshot is admitted after the read.
            if hashfile(path) != sha:
                raise ValueError("Original source changed during capture")
            stats["source_checksum_unchanged"] = True
            stats["unresolved_links"] = db.execute(
                "select count(*) from links where edition_id=? and state='unresolved'",
                (edition.id,),
            ).fetchone()[0]
            db.commit()
            summaries.append(stats)
            progress(
                {
                    "event": "whole_book_capture",
                    "calibre_id": bid,
                    "nodes": stats["nodes"],
                }
            )
        return summaries
    finally:
        db.close()
