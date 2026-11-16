"""Web UI served by FastAPI (SAD 3.3, 4.5) and its safety rules (SAD 3.9, OT-SR-006).

- /ui returns the page, every asset it loads exists, / redirects to /ui/, /docs still works
- no JavaScript file puts non-constant data into the page as HTML
- no CDN or other external address, and the token is never put in localStorage
"""
import re
from pathlib import Path

import pytest

from tests.api_fixtures import client  # noqa: F401

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
JS_FILES = sorted((STATIC / "js").glob("*.js"))


# ---------- serving ----------


def test_ui_page_is_served_as_html(client):
    response = client.get("/ui/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>OT Management System</title>" in response.text


def test_ui_without_slash_redirects_to_the_page(client):
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/ui/")
    assert client.get("/ui").status_code == 200


def test_root_redirects_to_the_ui(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/ui/"


def test_api_docs_still_work(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/surgeries" in paths
    assert "/" not in paths  # the redirect is hidden from the API docs


def test_every_asset_in_index_html_resolves(client):
    html = client.get("/ui/").text
    assets = re.findall(r'(?:src|href)="(/ui/[^"]+)"', html)
    assert "/ui/css/style.css" in assets and "/ui/js/app.js" in assets
    for asset in assets:
        response = client.get(asset)
        assert response.status_code == 200, asset


def test_every_js_import_resolves(client):
    """app.js imports the other modules; a typo in a file name would break the whole UI."""
    for path in JS_FILES:
        for name in re.findall(r'from "\./([\w-]+\.js)"', path.read_text()):
            response = client.get(f"/ui/js/{name}")
            assert response.status_code == 200, f"{path.name} imports {name}"
            assert "javascript" in response.headers["content-type"]


def test_missing_asset_gives_404(client):
    assert client.get("/ui/js/does-not-exist.js").status_code == 404


# ---------- safety: no API data inserted as HTML ----------

# Ways to turn a string into HTML or code. Only innerHTML = "<constant text>" would be harmless,
# and the UI does not even use that: el() in dom.js always uses textContent.
CONSTANT_STRING = r"""(?:"[^"\\]*"|'[^'\\]*'|`[^`$\\]*`)"""
UNSAFE = [
    re.compile(r"\.(?:innerHTML|outerHTML)\s*\+?=(?!\s*" + CONSTANT_STRING + r"\s*;?\s*$)"),
    re.compile(r"\.insertAdjacentHTML\s*\("),
    re.compile(r"\bdocument\.write(?:ln)?\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bnew\s+Function\s*\("),
    re.compile(r"\.setAttribute\(\s*[\"']on\w+"),  # inline event handler from a string
]


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", source)


def unsafe_lines(source: str):
    code = strip_comments(source)
    return [line.strip() for line in code.splitlines() if any(pattern.search(line) for pattern in UNSAFE)]


@pytest.mark.parametrize("path", JS_FILES, ids=lambda path: path.name)
def test_js_never_inserts_non_constant_html(path):
    assert unsafe_lines(path.read_text()) == []


@pytest.mark.parametrize(
    "line, unsafe",
    [
        ("box.innerHTML = name;", True),
        ("box.innerHTML = `<b>${name}</b>`;", True),
        ("box.innerHTML += '<li>' + item;", True),
        ("box.outerHTML = data.html;", True),
        ("row.insertAdjacentHTML('beforeend', x);", True),
        ("document.write(text);", True),
        ("eval(code);", True),
        ("node.setAttribute('onclick', code);", True),
        ("box.innerHTML = '';", False),       # a constant is harmless
        ("box.textContent = name;", False),
        ("// box.innerHTML = name;", False),  # comments are ignored
    ],
)
def test_the_html_check_itself_works(line, unsafe):
    assert bool(unsafe_lines(line + "\n")) is unsafe


# ---------- safety: no external code, token kept out of localStorage ----------


def test_no_cdn_or_external_address_in_static_files():
    for path in STATIC.rglob("*"):
        if path.is_file():
            assert not re.search(r"https?://", path.read_text()), f"external address in {path.name}"


def test_content_security_policy_allows_only_this_server():
    html = (STATIC / "index.html").read_text()
    assert "Content-Security-Policy" in html
    assert "script-src 'self'" in html
    assert "<script>" not in html  # no inline script


def test_token_is_never_put_in_local_storage():
    """SAD 3.9: the token lives in sessionStorage only; localStorage holds the theme choice."""
    for path in JS_FILES:
        code = strip_comments(path.read_text())
        for key in re.findall(r"localStorage\.setItem\(\s*\"([^\"]+)\"", code):
            assert key == "otms.theme", f"{path.name} stores {key} in localStorage"
        assert "otms.token" not in code or path.name == "api.js"
    api_js = (STATIC / "js" / "api.js").read_text()
    assert "sessionStorage.setItem(TOKEN_KEY" in api_js
