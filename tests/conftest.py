from pathlib import Path
import time
import uuid
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt
from cookbook.build import create_index, add_content
from cookbook.publication import Entry, Manifest, Runtime, publish
from cookbook.storage import LocalStore, digest_file
from cookbook.library import Library


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public


@pytest.fixture
def mint(keys):
    def token(**changes):
        claims = {
            "iss": "https://issuer.example/",
            "aud": "http://127.0.0.1:8765/mcp",
            "sub": "user-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "scope": "library:read",
        }
        claims.update(changes)
        return jwt.encode(claims, keys[0], algorithm="RS256")

    return token


def fixture_build(
    root: Path, *, count=1, publication_id=None, section_count=1, repeats=1000
):
    root.mkdir(parents=True)
    pub = publication_id or uuid.uuid4().hex
    db = create_index(root / "index.sqlite", pub)
    from PIL import Image

    im = Image.new("RGB", (300, 200), "orange")
    im.save(root / "image.jpg")
    inputs = {
        "runtime/index.sqlite": root / "index.sqlite",
        "assets/image": root / "image.jpg",
    }
    for i in range(count):
        text = f"Synthetic bean recipe {i}. Use 1/2 teaspoon salt and 200 grams beans. Simmer 20 minutes. "
        content = (text * repeats * section_count).encode()
        p = root / f"original-{i}.txt"
        p.write_bytes(content)
        sha, size = digest_file(p)
        source = "epub:" + sha
        logical = f"backup/book-{i}.txt"
        inputs[logical] = p
        sections = [
            {
                "id": f"section-{i}" if j == 0 else f"section-{i}-{j}",
                "title": f"Beans {i} recipe {j}",
                "text": text * repeats,
                "locator": {
                    "kind": "epub",
                    "document": f"chapter-{j}.xhtml",
                    "anchor": "beans",
                    "text_offset": 0,
                },
                "provenance": "native",
                "kind": "recipe",
                "images": ["image-" + str(i)],
            }
            for j in range(section_count)
        ]
        add_content(
            db,
            source,
            "EPUB",
            sha,
            logical,
            sections,
            [
                {
                    "id": "image-" + str(i),
                    "asset": "assets/image",
                    "document": "chapter.xhtml",
                    "caption": "Synthetic beans",
                }
            ],
            [{"title": "Beans", "depth": 0, "section_id": f"section-{i}"}],
        )
        db.execute(
            "insert into books values(?,?,?,?,?,?)",
            (
                f"book-{i}",
                i,
                f"Synthetic Beans {i}",
                '["Test Author"]',
                '["cooking"]',
                source,
            ),
        )
        if i == 0:
            db.execute(
                "insert into books values(?,?,?,?,?,?)",
                ("alias", 900, "Alias Beans", '["Test Author"]', '["cooking"]', source),
            )
    db.commit()
    db.close()
    from cookbook.quality import QUALITY_PATH, make_report
    from cookbook.storage import atomic_write, canonical

    atomic_write(root / "ocr-review.json", canonical(make_report(pub, [])))
    inputs[QUALITY_PATH] = root / "ocr-review.json"
    entries = []
    for logical, p in inputs.items():
        sha, size = digest_file(p)
        entries.append(
            Entry(
                path=logical,
                sha256=sha,
                size=size,
                role="runtime"
                if logical.startswith("runtime")
                else "backup"
                if logical.startswith(("backup", "quality"))
                else "asset",
            )
        )
    return Manifest(
        publication_id=pub, created_at="2026-09-11T00:00:00Z", files=entries
    ), inputs


@pytest.fixture
def published(tmp_path):
    m, inputs = fixture_build(tmp_path / "build")
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    r = publish(store, m, inputs, expected_version=None, activate=runtime.activate)
    return m, inputs, store, runtime, Library(runtime), r


@pytest.fixture
def manifest_loads(monkeypatch):
    """Count actual local manifest opens and validation, not cache internals."""
    counts = {"read": 0, "parse": 0}
    original_open = Path.open
    original_parse = Manifest.model_validate_json

    def opened(path, *args, **kwargs):
        if path.name == "manifest.json" and args and args[0] == "rb":
            counts["read"] += 1
        return original_open(path, *args, **kwargs)

    def parsed(raw, *args, **kwargs):
        counts["parse"] += 1
        return original_parse(raw, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(Manifest, "model_validate_json", parsed)
    return counts
