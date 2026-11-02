"""Loopback-only, synthetic reader demo. Never deploy this development adapter.

Run: uv run python scripts/preview_reader.py
Uses the real reader routes with invented publications and local metadata stores.
Only this adapter translates localhost HTTP to the reader's HTTPS contract and
maps secure cookies to demo-only cookies. Production authentication is unchanged.
"""

import json
import os
import textwrap
import time
from pathlib import Path
from urllib.parse import urlencode

import jwt
import uvicorn
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from PIL import Image, ImageDraw, ImageFont
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from cookbook.build import add_content, create_index
from cookbook.library import Library
from cookbook.owner_reports import OwnerReports
from cookbook.publication import Entry, Manifest, Runtime, publish
from cookbook.quality import QUALITY_PATH, make_report
from cookbook.reader import Reader, ReaderConfig
from cookbook.reader_personal import PersonalState
from cookbook.server import JWTVerifier, create_app
from cookbook.storage import LocalStore, canonical, digest_file

PORT = 8766
HOST = f"localhost:{PORT}"
ORIGIN = "https://" + HOST
BOOKS = [
    (
        "weeknight",
        "The Weeknight Table",
        "Mara Ellis",
        "EPUB",
        [
            (
                "Lemony white beans with greens",
                "Serves 2 · About 25 minutes\n\nA warm bowl for the evening when the fridge looks almost empty. Keep the beans soft and the lemon bright.\n\nINGREDIENTS\n2 tablespoons olive oil\n2 garlic cloves, thinly sliced\n2 cans white beans, drained\n150 g kale or spinach\n1 lemon, zest and juice\nSalt and black pepper\nToast, to serve\n\nMETHOD\n1. Warm the oil in a wide pan. Add the garlic and cook gently until fragrant.\n2. Add the beans and 150 ml water. Simmer for 8 minutes, crushing a few beans to thicken the broth.\n3. Fold in the greens and cook until tender.\n4. Stir in the lemon zest and a little juice. Taste, season, and spoon over toast.\n\nAT THE TABLE\nFinish with more olive oil. A spoonful of the green herb sauce in the next section is lovely here.",
            ),
            (
                "Green herb sauce",
                "Makes a small bowl · About 10 minutes\n\nINGREDIENTS\n1 large handful parsley\n1 small handful basil\n1 tablespoon capers\n1 teaspoon Dijon mustard\n3 tablespoons olive oil\n1 tablespoon lemon juice\n\nMETHOD\nChop the herbs and capers finely. Stir in the mustard, oil and lemon juice. Taste before adding salt.\n\nSpoon over white beans, roast vegetables, or eggs. The sauce keeps in the refrigerator for two days.",
            ),
            (
                "A slower kind of supper",
                "A pantry supper starts with one good thing and enough time to taste it. A tin of beans, a handful of greens, a lemon: none asks much of you.\n\n"
                + "Let the pot simmer gently while you set the table. Add water when the beans look dry; add salt when the broth tastes flat. Save the lemon until the end so its freshness survives. The point is a meal you can make again without reading every line.\n\n"
                * 20,
            ),
        ],
    ),
    (
        "seasonal",
        "A Small Seasonal Kitchen",
        "Theo Lane",
        "EPUB",
        [
            (
                "Roast carrots with yogurt and cumin",
                "Serves 4 · About 40 minutes\n\nINGREDIENTS\n750 g carrots\n2 tablespoons olive oil\n1 teaspoon cumin seeds\n150 g plain yogurt\nHalf a lemon\nA handful of parsley\n\nMETHOD\n1. Heat the oven to 220°C. Scrub the carrots and halve the thick ones lengthwise.\n2. Toss with olive oil, cumin, and salt. Roast for 30 minutes, turning once.\n3. Season the yogurt with lemon juice and salt. Spread on a plate, add the carrots, and scatter with parsley.",
            ),
            (
                "Apple and oat crumble",
                "Serves 4 · About 45 minutes\n\nINGREDIENTS\n4 apples\n1 tablespoon lemon juice\n60 g rolled oats\n60 g flour\n50 g butter\n40 g brown sugar\n\nMETHOD\nHeat the oven to 190°C. Slice the apples into a small baking dish and add lemon juice. Rub the butter into the flour, then stir in the oats and sugar. Scatter over the apples and bake for 30–35 minutes, until golden. Let it stand before serving.",
            ),
        ],
    ),
    (
        "notebook",
        "The Soup Notebook",
        "Nora Vale",
        "PDF",
        [
            (
                "Tomato and lentil soup",
                "Serves 4 · About 35 minutes\n\nINGREDIENTS\n1 onion, chopped\n2 tablespoons olive oil\n150 g red lentils\n1 can chopped tomatoes\n750 ml vegetable stock\n[unresolved amount: ground cumin]\n\nMETHOD\n1. Soften the onion in olive oil for 8 minutes.\n2. Add the lentils, tomatoes, stock and cumin.\n3. Simmer gently for 20 minutes, stirring occasionally, until the lentils are tender.\n4. Taste for salt. Serve with lemon and bread.\n\nThis sample deliberately includes an uncertain quantity. Inspect the original or submit a report to try the review controls.",
            ),
        ],
    ),
]


def page_image(path, title, text):
    image = Image.new("RGB", (1000, 1400), "#fffdf5")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 22)
        heading = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 30
        )
    except OSError:
        font = ImageFont.load_default(size=22)
        heading = ImageFont.load_default(size=30)
    draw.text(
        (70, 55), "LOCAL PREVIEW · INVENTED SAMPLE PAGE", fill="#776b57", font=font
    )
    draw.text((70, 120), title, fill="#263a2e", font=heading)
    lines = []
    for paragraph in text.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=69) or [""])
    draw.multiline_text(
        (70, 200), "\n".join(lines[:35]), fill="#292a26", font=font, spacing=8
    )
    draw.text(
        (70, 1320),
        "Synthetic source — no real cookbook content",
        fill="#776b57",
        font=font,
    )
    image.save(path, "PNG")


def sample_library(root):
    store = LocalStore(root / "library")
    runtime = Runtime(store, root / "runtime")
    pub = "b98de000000000000000000000000002"
    if runtime.active() and runtime.active()["publication_id"] == pub:
        runtime.resume_cached()
        return runtime
    build = root / "samples-v2"
    build.mkdir(parents=True, exist_ok=True)
    db = create_index(build / "index.sqlite", pub)
    inputs = {"runtime/index.sqlite": build / "index.sqlite"}
    for number, (bid, title, author, fmt, recipes) in enumerate(BOOKS):
        original = build / (bid + ".txt")
        original.write_text("\n\n".join(t + "\n" + body for t, body in recipes))
        sha, _ = digest_file(original)
        source = fmt.lower() + ":" + sha
        original_key = "backup/" + bid + ".txt"
        inputs[original_key] = original
        sections, images, toc = [], [], []
        for index, (recipe, body) in enumerate(recipes):
            sid = f"{bid}-{index}"
            iid = "image-" + sid
            asset = build / (sid + ".png")
            page_image(asset, recipe, body)
            inputs["assets/" + iid] = asset
            locator = {"kind": "epub", "document": sid + ".xhtml", "anchor": "start"}
            section = {
                "id": sid,
                "title": recipe,
                "text": body,
                "locator": locator,
                "provenance": "native synthetic sample",
                "kind": "recipe",
                "images": [iid],
            }
            if fmt == "PDF":
                locator = {"kind": "page", "physical_page": 1}
                section.update(
                    kind="page",
                    locator=locator,
                    provenance="agent transcription, unapproved",
                    transcription={
                        "label": "Synthetic transcription — unapproved",
                        "check_regions": [
                            {
                                "physical_page": 1,
                                "box": [0.06, 0.32, 0.8, 0.49],
                                "state": "unresolved",
                            }
                        ],
                        "corrections": [],
                    },
                )
            sections.append(section)
            images.append(
                {
                    "id": iid,
                    "asset": "assets/" + iid,
                    "document": sid + ".xhtml",
                    "caption": "Sample original: " + recipe,
                }
            )
            toc.append({"title": recipe, "depth": 0, "section_id": sid})
        add_content(db, source, fmt, sha, original_key, sections, images, toc)
        db.execute(
            "insert into books values(?,?,?,?,?,?)",
            (bid, number, title, json.dumps([author]), '["sample"]', source),
        )
    db.commit()
    db.close()
    quality = build / "ocr-review.json"
    quality.write_bytes(canonical(make_report(pub, [])))
    inputs[QUALITY_PATH] = quality
    entries = [
        Entry(
            path=key,
            sha256=digest_file(path)[0],
            size=path.stat().st_size,
            role="runtime"
            if key.startswith("runtime/")
            else "asset"
            if key.startswith("assets/")
            else "backup",
        )
        for key, path in inputs.items()
    ]
    manifest = Manifest(
        publication_id=pub, created_at="2026-11-01T00:00:00Z", files=entries
    )
    publish(
        store,
        manifest,
        inputs,
        expected_version=store.read_version("control/active.json")[1],
        activate=runtime.activate,
    )
    return runtime


class SampleReader(Reader):
    def page(self, body, **options):
        return super().page(
            '<aside aria-label="Preview information"><p><strong>Local preview</strong>'
            " · Sample books · Simulated sign-in</p></aside>" + body,
            **options,
        )


class SampleLibrary(Library):
    """Return the pre-created synthetic page; never invoke a source renderer."""

    def get_page(
        self, publication_id, book_id, source_id, physical_page, edge=1600, region=None
    ):
        import io

        from cookbook.library import crop_region

        pub = self.publication(publication_id)
        with self.db(pub) as db:
            book = self.book(db, book_id, source_id)
            section = self.page_row(db, source_id, physical_page)
            image = db.execute(
                "select asset from images where source_id=? limit 1", (source_id,)
            ).fetchone()
            path = self.cached(pub, image[0])
            with Image.open(path) as opened:
                pixels = opened.convert("RGB")
                if region:
                    pixels = crop_region(pixels, region, edge)
                output = io.BytesIO()
                pixels.save(output, "JPEG")
            return {"citation": self.citation(pub, book, section)}, output.getvalue()


def app(state_root=None):
    root = Path(
        state_root or (Path.home() / "cookbook-mcp-data/previews/reader-spec98")
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime = sample_library(root)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JWTVerifier(
        issuer=ORIGIN + "/",
        audience=ORIGIN,
        subjects=["sample-reader"],
        public_key=private.public_key(),
    )

    class SampleIdentity:
        async def exchange(self, code, verifier, nonce):
            if code != "local-sample":
                raise ValueError("invalid sample code")
            return await self.renew(None)

        async def renew(self, token):
            now = int(time.time())
            return {
                "access_token": jwt.encode(
                    {
                        "iss": ORIGIN + "/",
                        "aud": ORIGIN,
                        "sub": "sample-reader",
                        "iat": now,
                        "exp": now + 3600,
                        "scope": "library:read",
                    },
                    private,
                    algorithm="RS256",
                ),
                "refresh_token": "sample",
            }

        async def revoke(self, token):
            pass

    keyfile = root / "sample-session.key"
    if not keyfile.exists():
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(Fernet.generate_key())
    reader = SampleReader(
        ReaderConfig(
            origin=ORIGIN, client_id="local-sample", client_secret="local-sample"
        ),
        verifier,
        LocalStore(root / "sessions"),
        keyfile.read_bytes(),
        identity=SampleIdentity(),
        owner_reports=OwnerReports(LocalStore(root / "reports")),
        personal_state=PersonalState(LocalStore(root / "personal")),
    )
    production = create_app(SampleLibrary(runtime), verifier, reader=reader)

    async def authorize(request):
        return RedirectResponse(
            "/reader/callback?"
            + urlencode(
                {
                    "code": "local-sample",
                    "state": request.query_params.get("state", ""),
                    "iss": ORIGIN + "/",
                }
            ),
            status_code=303,
        )

    async def sample_logout(request):
        return RedirectResponse("/reader", status_code=303)

    production.routes.insert(0, Route("/authorize", authorize))
    production.routes.insert(0, Route("/v2/logout", sample_logout))

    async def local_only(scope, receive, send):
        if scope["type"] != "http":
            return await production(scope, receive, send)
        headers = dict(scope["headers"])
        if (
            scope.get("client", ("",))[0] not in ("127.0.0.1", "::1", "testclient")
            or headers.get(b"host") != HOST.encode()
        ):
            return await Response("Local synthetic preview only", status_code=403)(
                scope, receive, send
            )
        if b"origin" in headers:
            if headers[b"origin"] != ("http://" + HOST).encode():
                return await Response(status_code=403)(scope, receive, send)
            headers[b"origin"] = ORIGIN.encode()
        if b"cookie" in headers:
            headers[b"cookie"] = headers[b"cookie"].replace(
                b"preview-reader", b"__Host-reader"
            )
        scope = {**scope, "scheme": "https", "headers": list(headers.items())}

        async def demo_send(message):
            if message["type"] == "http.response.start":
                rewritten = []
                for key, value in message.get("headers", []):
                    if key == b"strict-transport-security":
                        continue
                    if key == b"location":
                        value = value.replace(
                            ORIGIN.encode(), ("http://" + HOST).encode(), 1
                        )
                    if key == b"set-cookie":
                        value = value.replace(
                            b"__Host-reader", b"preview-reader"
                        ).replace(b"; Secure", b"")
                    rewritten.append((key, value))
                message = {**message, "headers": rewritten}
            await send(message)

        await production(scope, receive, demo_send)

    return local_only


if __name__ == "__main__":
    print(f"Synthetic reader preview: http://{HOST}/reader/login", flush=True)
    uvicorn.run(
        app(), host="127.0.0.1", port=PORT, access_log=False, proxy_headers=False
    )
