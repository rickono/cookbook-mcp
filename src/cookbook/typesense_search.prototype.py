"""PROTOTYPE: real local Typesense versus SQLite keyword recipe retrieval.

Existing extracted snapshot only. No OCR, ingestion, embeddings or model calls.
All index data, source packages and owner judgments stay outside Git.
"""
# ruff: noqa: N999
from __future__ import annotations
import argparse
import atexit
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit, urlencode, quote
from urllib.request import Request, urlopen

VERSION = "30.2"
DEFAULT_DATA = Path.home() / "cookbook-mcp-data/poc/recipe-catalog-20-20261006/whole-book-model"
DEFAULT_OUTPUT = Path.home() / "cookbook-mcp-data/poc/typesense-prototype-20261009"
COLLECTION = "recipe_candidates_prototype"

STOP = {
    "a",
    "an",
    "the",
    "i",
    "me",
    "my",
    "we",
    "want",
    "looking",
    "for",
    "find",
    "something",
    "recipe",
    "recipes",
    "book",
    "books",
    "cookbook",
    "cookbooks",
    "please",
    "can",
    "could",
    "would",
    "that",
    "is",
    "are",
    "and",
    "or",
    "with",
    "of",
    "to",
    "in",
    "on",
    "be",
    "make",
    "good",
    "easy",
    "elegant",
    "best",
    "really",
    "very",
    "dessert",
}

EXPANSIONS = {
    "dessert": "cake tart pudding custard mousse sorbet ice cream chocolate cookies pavlova meringue panna cotta cheesecake sweet",
    "vegetarian": "vegetable mushroom aubergine eggplant lentil chickpea cauliflower squash salad",
    "cocktail": "cocktail drink gin rum whisky whiskey vodka tequila vermouth",
    "chicken": "chicken poultry",
    "quick": "quick simple minute",
    "easy": "easy simple straightforward",
    "pair": "pair pairing flavor flavours affinity affinities",
    "pairing": "pair pairing flavor flavours affinity affinities",
}

def read_only(path):
    c = sqlite3.connect("file:" + str(path) + "?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c

class Corpus:
    def __init__(self, data):
        self.data = data
        self.path = data / "whole-books.sqlite"
        with read_only(self.path) as c:
            self.books = [
                dict(r)
                for r in c.execute(
                    "select id,calibre_id,title from editions order by calibre_id"
                )
            ]
            self.entities = {
                r["id"]: json.loads(r["payload"])
                for r in c.execute("select id,payload from entities")
            }
            self.recipes = {
                i: e for i, e in self.entities.items() if e["kind"] == "recipe"
            }
            self.spans = {
                r["id"]: json.loads(r["payload"])
                for r in c.execute("select id,payload from spans")
            }
        self.book_map = {b["id"]: b for b in self.books}
        self.snapshot = json.loads((data / "validation-report.json").read_text())[
            "model_snapshot"
        ]["id"]
        old = data / "recipe-candidates.json"
        if not old.exists():
            old = data.parent / "recipe-boundaries-20261004/candidates.json"
        self.old = {}
        if old.exists():
            for r in json.loads(old.read_text()):
                self.old[(r["book_id"], r["title"], r["start_xpath"])] = r
        self.packages = {}
        self.package_lock = threading.RLock()

    def selection(self, span_ids):
        texts, citations, images = [], [], 0
        with read_only(self.path) as c:
            for sid in span_ids:
                for part in self.spans[sid]["parts"]:
                    a = c.execute(
                        "select * from nodes where id=?", (part["start"]["node_id"],)
                    ).fetchone()
                    b = c.execute(
                        "select * from nodes where id=?", (part["end"]["node_id"],)
                    ).fetchone()
                    if (
                        part["start"]["side"] != "before"
                        or part["end"]["side"] != "after"
                    ):
                        raise ValueError(
                            "Prototype only executes whole-node selections"
                        )
                    if (
                        a["document_id"] != b["document_id"]
                        or a["preorder"] > b["subtree_end"]
                    ):
                        raise ValueError("Invalid source selection")
                    out = []
                    for n in c.execute(
                        "select node_kind,content_kind,text,json_extract(payload,'$.source_tag') as source_tag from nodes where document_id=? and preorder between ? and ? order by preorder",
                        (a["document_id"], a["preorder"], b["subtree_end"]),
                    ):
                        if n["node_kind"] == "text":
                            out.append(n["text"])
                        elif n["content_kind"] == "image":
                            images += 1
                            out.append("[uninterpreted inline image]")
                        elif (
                            n["content_kind"] == "line_break"
                            or n["content_kind"]
                            in (
                                "paragraph",
                                "heading",
                                "table_row",
                                "table_cell",
                                "list_item",
                            )
                            or n["content_kind"] == "container"
                            and re.search(
                                r"(?:^|})(?:div|section|article)$",
                                n["source_tag"] or "",
                            )
                        ):
                            out.append("\n")
                    text = re.sub(r"[ \t]+", " ", "".join(out))
                    texts.append(re.sub(r"\n\s*\n+", "\n\n", text).strip())
                    d = c.execute(
                        "select path from documents where id=?", (part["document_id"],)
                    ).fetchone()
                    citations.append(
                        {
                            "span_id": sid,
                            "document": d["path"],
                            "start_xpath": a["xpath"],
                            "end_xpath": b["xpath"],
                        }
                    )
        return "\n\n".join(texts), citations, images

    def package(self, ident):
        with self.package_lock:
            if ident in self.packages:
                return self.packages[ident]
            e = self.entities[ident]
            spans = (
                e.get("content_span_ids")
                or e.get("source_span_ids")
                or e["evidence_span_ids"]
            )
            text, citations, images = self.selection(spans)
            book = self.book_map[e["edition_id"]]
            p = {
                "id": ident,
                "kind": e["kind"],
                "title": (e.get("title") or e.get("label") or {}).get("value")
                or "Untitled source record",
                "book": book["title"],
                "book_id": book["calibre_id"],
                "edition_id": e["edition_id"],
                "text": text,
                "citations": citations,
                "source_state": e["state"],
                "model_snapshot_id": self.snapshot,
                "uninterpreted_images": images,
                "supporting_work_state": e.get("supporting_work_state", "not assessed"),
                "linked_sources": [],
                "typed_parts": [],
                "typed_uses": [],
            }
            for child in self.entities.values():
                if (
                    child.get("recipe_id") == ident
                    or child.get("source_recipe_id") == ident
                ):
                    if child["kind"] == "recipe_use":
                        use = dict(child)
                        target = (
                            child.get("selected_part_id")
                            or child.get("selected_formulation_id")
                            or child.get("target_recipe_id")
                        )
                        if target:
                            te = self.entities[target]
                            ts = te.get("content_span_ids") or te["evidence_span_ids"]
                            target_text, tc, ti = self.selection(ts)
                            use["selected_source"] = {
                                "kind": te["kind"],
                                "text": target_text,
                                "citations": tc,
                                "uninterpreted_images": ti,
                            }
                        p["typed_uses"].append(use)
                    elif child["kind"] == "recipe_part":
                        p["typed_parts"].append(child)
            old = self.old.get(
                (e["edition_id"], p["title"], citations[0]["start_xpath"])
            )
            if old:
                seen = set()
                for link in old["references"]:
                    if link.get("source_role") == "image" or not link.get(
                        "target_text"
                    ):
                        continue
                    sig = (link.get("target_document"), link.get("target_anchor"))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    p["linked_sources"].append(
                        {
                            k: link[k]
                            for k in (
                                "label",
                                "href",
                                "source_role",
                                "source_text",
                                "target_document",
                                "target_anchor",
                                "resolution",
                                "target_text",
                            )
                            if k in link
                        }
                    )
            self.packages[ident] = p
            return p


def keywords(question, expanded=True):
    words = re.findall(r"\w+", question.lower())
    stop = STOP if expanded else STOP - {"easy", "elegant", "dessert"}
    terms = [w for w in words if w not in stop and len(w) > 1]
    if expanded:
        for trigger, additions in EXPANSIONS.items():
            if trigger in words:
                terms.extend(additions.split())
    return list(dict.fromkeys(terms))[:40]


def check_port(port):
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


class Trial:
    def __init__(self, data, output, engine_port, peer_port):
        self.data, self.output = data.resolve(), output.resolve()
        root = Path(__file__).resolve().parents[2]
        if self.output.is_relative_to(root) or self.data.is_relative_to(root):
            raise ValueError("Keep source records and trial output outside the checkout")
        self.output.mkdir(parents=True, exist_ok=True)
        self.judgments_path = self.output / "owner-judgments.json"
        self.judgments = json.loads(self.judgments_path.read_text()) if self.judgments_path.exists() else {}
        self.lock = threading.RLock()
        check_port(engine_port)
        check_port(peer_port)
        self.key = secrets.token_urlsafe(32)
        self.url = f"http://127.0.0.1:{engine_port}"
        self.process = None
        self.log = None
        print("Reading the existing source snapshot…", flush=True)
        start = time.perf_counter()
        self.corpus = Corpus(data)
        self.packages = [self.corpus.package(i) for i in self.corpus.recipes]
        self.by_id = {p["id"]: p for p in self.packages}
        self.books = sorted({p["book_id"]: p["book"] for p in self.packages}.items(), key=lambda b: b[1])
        self.index = sqlite3.connect(":memory:", check_same_thread=False)
        self.index.execute("create virtual table candidates using fts5(id UNINDEXED,book_id UNINDEXED,title,text)")
        self.index.executemany("insert into candidates values(?,?,?,?)", [(p["id"],p["book_id"],p["title"],p["text"]) for p in self.packages])
        self.index.commit()
        print(f"Loaded {len(self.packages)} candidates from {len(self.books)} books in {time.perf_counter()-start:.1f}s", flush=True)
        binary = self.prepare_binary()
        run = self.output / ("run-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2))
        run.mkdir(mode=0o700)
        self.run = run
        (run / "index").mkdir()
        config = run / "typesense.ini"
        config.write_text(f"[server]\ndata-dir={run / 'index'}\napi-key={self.key}\napi-address=127.0.0.1\napi-port={engine_port}\npeering-address=127.0.0.1\npeering-port={peer_port}\nthread-pool-size=2\nnum-collections-parallel-load=1\nmax-indexing-concurrency=2\nenable-cors=false\nenable-access-logging=false\nenable-search-logging=false\nenable-search-analytics=false\n")
        config.chmod(0o600)
        self.log = (run / "engine.log").open("w")
        env = {k:v for k,v in os.environ.items() if not k.startswith("TYPESENSE_")}
        self.process = subprocess.Popen([str(binary),"--config",str(config)], stdout=self.log, stderr=subprocess.STDOUT, env=env)
        atexit.register(self.close)
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError(f"Typesense stopped; inspect {run / 'engine.log'}")
            try:
                if self.call("GET","/health").get("ok"):
                    break
            except (URLError, OSError):
                pass
            time.sleep(.1)
        else:
            raise RuntimeError("Typesense did not become healthy")
        # Deliberately contains no vector, embedding, auto-embed or model configuration.
        schema = {"name":COLLECTION,"fields":[
            {"name":"title","type":"string"}, {"name":"text","type":"string"},
            {"name":"book","type":"string","facet":True}, {"name":"book_id","type":"int32","facet":True},
            {"name":"source_state","type":"string","facet":True}, {"name":"uninterpreted_images","type":"int32"}]}
        self.call("POST","/collections",schema)
        records = [{k:p[k] for k in ("id","title","text","book","book_id","source_state","uninterpreted_images")} for p in self.packages]
        lines = "\n".join(json.dumps(r,ensure_ascii=False) for r in records)
        imported = self.call("POST",f"/collections/{COLLECTION}/documents/import?action=create",lines,raw=True)
        status = [json.loads(line) for line in imported.splitlines() if line.strip()]
        failed = [r for r in status if not r.get("success")]
        if failed or len(status) != len(records):
            (run / "import-status.json").write_text(json.dumps(status))
            raise RuntimeError(f"Typesense import failed; inspect {run / 'import-status.json'}")
        self.version = self.call("GET","/debug").get("version",VERSION)
        (run / "manifest.json").write_text(json.dumps({"snapshot":self.corpus.snapshot,"candidates":len(records),"books":len(self.books),"typesense_version":self.version,"mode":"keyword only; no OCR/inference", "schema":schema},indent=2))
        print(f"Typesense {self.version}: indexed {len(records)} records. Private trial data: {run}",flush=True)

    def prepare_binary(self):
        tools = self.output / "tools"
        tools.mkdir(exist_ok=True)
        binary = tools / "typesense-server"
        if binary.exists():
            return binary
        machine = {"arm64":"arm64","aarch64":"arm64","x86_64":"amd64"}.get(platform.machine())
        system = {"Darwin":"darwin","Linux":"linux"}.get(platform.system())
        if not machine or not system:
            raise ValueError("This prototype needs an official macOS or Linux Typesense binary")
        url = f"https://dl.typesense.org/releases/{VERSION}/typesense-server-{VERSION}-{system}-{machine}.tar.gz"
        archive = tools / f"typesense-{VERSION}.tar.gz"
        print(f"Downloading the official Typesense {VERSION} binary…",flush=True)
        with urlopen(url,timeout=60) as r, archive.open("wb") as f:
            while chunk := r.read(1024*1024):
                f.write(chunk)
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                if Path(member.name).name == "typesense-server" and member.isfile():
                    binary.write_bytes(t.extractfile(member).read())
                    binary.chmod(0o700)
                    return binary
        raise ValueError("Official archive did not contain typesense-server")

    def call(self, method, path, data=None, raw=False):
        body = data.encode() if isinstance(data,str) else json.dumps(data).encode() if data is not None else None
        request = Request(self.url+path,data=body,method=method,headers={"X-TYPESENSE-API-KEY":self.key,"Content-Type":"text/plain" if raw else "application/json"})
        with urlopen(request,timeout=60) as r:
            value = r.read().decode()
        return value if raw else json.loads(value)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log:
            self.log.close()
            self.log = None

    @staticmethod
    def brief(p):
        return {k:p[k] for k in ("id","title","book","book_id","source_state","supporting_work_state","uninterpreted_images")} | {"snippet":p["text"][:340]}

    def case_key(self, params):
        # Candidate allowances and engine tuning are deliberately excluded: compare the same judgments while tuning.
        return hashlib.sha256(json.dumps({"request":params.get("query","").strip(),"book_id":int(params.get("book_id",0)),"snapshot":self.corpus.snapshot},sort_keys=True).encode()).hexdigest()

    def search(self, params):
        question = str(params.get("query","")).strip()[:1000]
        limit = max(1,min(100,int(params.get("limit",10))))
        book = int(params.get("book_id",0))
        weight = max(1,min(10,int(params.get("title_weight",5))))
        terms = keywords(question,bool(params.get("expanded",True)))
        common = {"request":question,"terms":terms,"result_allowance":limit,"case_key":self.case_key(params),"judgments":self.judgments.get(self.case_key(params),{}),"snapshot":self.corpus.snapshot}
        if not terms:
            return common | {"typesense":{"items":[],"found":0,"ms":0},"sqlite":{"items":[],"found":0,"ms":0},"note":"Add a dish, ingredient or recipe name."}
        ts_params = {"q":" ".join(terms),"query_by":"title,text","query_by_weights":f"{weight},1","per_page":limit,"num_typos":2 if params.get("typos",True) else 0,"drop_tokens_threshold":0 if params.get("require_all",False) else max(1,min(250,int(params.get("recovery_target",100)))),"prefix":"false","exclude_fields":"text","highlight_fields":"none","sort_by":"_text_match:desc","search_cutoff_ms":1500}
        if book:
            ts_params["filter_by"] = f"book_id:={book}"
        start = time.perf_counter()
        result = self.call("GET",f"/collections/{COLLECTION}/documents/search?"+urlencode(ts_params))
        ts_ms = (time.perf_counter()-start)*1000
        ts_items = [self.brief(self.by_id[h["document"]["id"]]) | {"engine_score":h.get("text_match"),"matched_tokens":h.get("text_match_info",{}).get("tokens_matched")} for h in result.get("hits",[])]
        query = " OR ".join('"'+t.replace('"','""')+'"' for t in terms)
        where, args = "candidates match ?", [query]
        if book:
            where += " and book_id=?"
            args.append(book)
        start = time.perf_counter()
        with self.lock:
            count = self.index.execute("select count(*) from candidates where "+where,args).fetchone()[0]
            rows = self.index.execute(f"select id,bm25(candidates,0,0,{weight},1) from candidates where "+where+" order by 2 limit ?",args+[limit]).fetchall()
        sqlite_ms = (time.perf_counter()-start)*1000
        sqlite_items = [self.brief(self.by_id[r[0]]) | {"engine_score":r[1]} for r in rows]
        return common | {"typesense":{"items":ts_items,"found":result.get("found",0),"ms":round(ts_ms,2),"engine_ms":result.get("search_time_ms",0),"cutoff":bool(result.get("search_cutoff",False)),"params":ts_params},"sqlite":{"items":sqlite_items,"found":count,"ms":round(sqlite_ms,2),"policy":"OR over the displayed keywords; BM25 title/body weighting"}}

    def lookup(self, query):
        words = re.findall(r"\w+",query.lower())
        matches = [p for p in self.packages if words and all(w in p["title"].lower() for w in words)]
        if not matches and query.strip():
            matches = sorted(self.packages,key=lambda p:difflib.SequenceMatcher(None,query.lower(),p["title"].lower()).ratio(),reverse=True)[:8]
        return [self.brief(p) for p in matches[:20]]

    def judge(self, params):
        ident = params["id"]
        if ident not in self.by_id:
            raise ValueError("Unknown recipe")
        book = int(params.get("book_id",0))
        if book and self.by_id[ident]["book_id"] != book:
            raise ValueError("That recipe is outside the selected book; clear the book filter to judge it here")
        key = self.case_key(params)
        with self.lock:
            case = self.judgments.setdefault(key,{"request":params.get("query","").strip(),"book_id":int(params.get("book_id",0)),"recipes":{}})
            entry = case["recipes"].setdefault(ident,{"title":self.by_id[ident]["title"],"book":self.by_id[ident]["book"]})
            if "fit" in params:
                if params["fit"] not in ("strong","compromise","unsuitable","unknown",""):
                    raise ValueError("Invalid fit judgment")
                entry["fit"] = params["fit"]
            if "must_find" in params:
                entry["must_find"] = bool(params["must_find"])
            if "uncertain" in params:
                entry["uncertain"] = bool(params["uncertain"])
            if not entry.get("fit") and not entry.get("must_find") and not entry.get("uncertain"):
                case["recipes"].pop(ident,None)
            tmp = self.judgments_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.judgments,ensure_ascii=False,indent=2))
            tmp.chmod(0o600)
            tmp.replace(self.judgments_path)
            return case


def handler_for(trial, html, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass

        def send(self,value,status=200,content_type="application/json"):
            body = value.encode() if isinstance(value,str) else json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type",content_type+"; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlsplit(self.path)
            query = parse_qs(u.query)
            try:
                if u.path == "/":
                    return self.send(html.read_text(),content_type="text/html")
                if u.path == "/api/state":
                    return self.send({"version":trial.version,"candidates":len(trial.packages),"books":[{"id":i,"title":t} for i,t in trial.books],"snapshot":trial.corpus.snapshot,"mode":"keyword","judgments_path":str(trial.judgments_path)})
                if u.path == "/api/recipe":
                    return self.send(trial.by_id[query["id"][0]])
                if u.path == "/api/lookup":
                    return self.send(trial.lookup(query.get("q",[""])[0]))
                if u.path == "/api/health":
                    return self.send(trial.call("GET","/health"))
                self.send({"error":"Not found"},404)
            except Exception as e:
                self.send({"error":str(e)},400)

        def do_POST(self):
            # Same-origin write/search requests only; never expose the engine administration key.
            if self.headers.get("Origin") not in (None,f"http://127.0.0.1:{port}",f"http://localhost:{port}"):
                return self.send({"error":"Use the local prototype page"},403)
            try:
                length = int(self.headers.get("Content-Length",0))
                if not 0 < length <= 16000:
                    raise ValueError("Invalid request size")
                params = json.loads(self.rfile.read(length))
                if self.path == "/api/search":
                    return self.send(trial.search(params))
                if self.path == "/api/judgment":
                    return self.send(trial.judge(params))
                self.send({"error":"Not found"},404)
            except HTTPError as e:
                self.send({"error":"Typesense: "+e.read().decode()[:800]},400)
            except Exception as e:
                self.send({"error":str(e)},400)
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=Path,default=DEFAULT_DATA)
    p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    p.add_argument("--port",type=int,default=8772)
    p.add_argument("--engine-port",type=int,default=8109)
    p.add_argument("--peer-port",type=int,default=8110)
    args = p.parse_args()
    check_port(args.port)
    trial = Trial(args.data,args.output,args.engine_port,args.peer_port)
    server = ThreadingHTTPServer(("127.0.0.1",args.port),handler_for(trial,Path(__file__).with_suffix(".html"),args.port))
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    print(f"Open http://127.0.0.1:{args.port}/ — Ctrl-C stops the page and its Typesense process",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        trial.close()


if __name__ == "__main__":
    main()
