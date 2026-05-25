#!/usr/bin/env python3
"""
Static checks for the Vite-built public site.

This suite is intended to run in Codespaces and CI without requiring Chrome.
It verifies source assets, the `_site` publish shape, generated local
references, and manifest icon references. Browser rendering remains covered by
tests/test_avatar_explorer.py.
"""

import html.parser
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
SITE_DIR = PROJECT_DIR / "_site"
INDEX_PATH = SITE_DIR / "index.html"

REQUIRED_SOURCE_ASSETS = [
    "avatar_builder_config.json",
    "avatar_builder_25_sept2025.riv",
    "manifest.webmanifest",
    "avatar-icon-192.png",
    "avatar-icon-512.png",
    "avatar_builder_body_unselected_dark.svg",
    "avatar_builder_face_unselected_dark.svg",
    "avatar_builder_hair_unselected_dark.svg",
    "avatar_builder_face_details_unselected_dark.svg",
    "avatar_builder_facial_hair_unselected_dark.svg",
    "avatar_builder_headwear_unselected_dark.svg",
    "avatar_builder_tshirt_unselected_dark.svg",
    "avatar_builder_background_unselected_dark.svg",
]

REQUIRED_SITE_FILES = [
    "index.html",
    ".nojekyll",
    "avatar_explorer.html",
    "avatar_builder_config.json",
    "avatar_builder_25_sept2025.riv",
    "manifest.webmanifest",
    "avatar-icon-192.png",
    "avatar-icon-512.png",
]


class StaticReferenceParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in ("src", "href"):
            value = attrs.get(attr)
            if value:
                self.refs.append((f"{tag} {attr}", value))


def is_local_reference(ref):
    if not ref or ref.startswith("#"):
        return False
    parsed = urlparse(ref)
    if parsed.scheme in ("http", "https", "data", "mailto", "tel"):
        return False
    return True


def normalize_reference(ref):
    parsed = urlparse(ref)
    path = parsed.path
    if path.startswith("/"):
        path = path[1:]
    return path


def run_site_build():
    result = subprocess.run(
        ["npm", "run", "build:site"],
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def read_site_file(rel):
    path = SITE_DIR / rel
    assert path.exists(), f"Missing built file: {rel}"
    return path.read_text(encoding="utf-8")


def parse_html(rel="index.html"):
    parser = StaticReferenceParser()
    parser.feed(read_site_file(rel))
    return parser


def assert_required_source_assets_exist():
    for rel in REQUIRED_SOURCE_ASSETS:
        path = ASSETS_DIR / rel
        assert path.exists(), f"Required source asset missing: {rel}"


def assert_pages_publish_shape():
    for rel in REQUIRED_SITE_FILES:
        assert (SITE_DIR / rel).exists(), f"Pages artifact missing: {rel}"
    assert any((SITE_DIR / "assets").glob("*.js")), "Vite JS bundle missing"
    assert any((SITE_DIR / "assets").glob("*.css")), "Vite CSS bundle missing"
    assert any((SITE_DIR / "assets").glob("*.wasm")), "Local Rive WASM bundle missing"


def assert_local_references_exist():
    refs = []
    for rel in ("index.html", "avatar_explorer.html"):
        parser = parse_html(rel)
        refs.extend((rel, source, ref) for source, ref in parser.refs)
        html = read_site_file(rel)
        for match in re.finditer(r"fetch\(\s*(['\"])(.*?)\1", html):
            refs.append((rel, "fetch", match.group(2)))

    missing = []
    for html_rel, source, ref in refs:
        if not is_local_reference(ref):
            continue
        rel = normalize_reference(ref)
        if not rel:
            continue
        base_dir = (SITE_DIR / html_rel).parent
        if not (base_dir / rel).exists():
            missing.append(f"{html_rel} {source}: {ref}")

    assert not missing, "Missing local references:\n" + "\n".join(missing)


def assert_manifest_icon_references_exist():
    manifest = json.loads(read_site_file("manifest.webmanifest"))
    missing = []
    for icon in manifest.get("icons", []):
        src = icon.get("src")
        if src and is_local_reference(src):
            rel = normalize_reference(src)
            if rel and not (SITE_DIR / rel).exists():
                missing.append(src)
    assert not missing, "Missing manifest icon references:\n" + "\n".join(missing)


def assert_no_unpkg_rive_runtime():
    offenders = []
    for path in [INDEX_PATH, *SITE_DIR.glob("assets/*.js"), SITE_DIR / "avatar_explorer.html"]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "unpkg.com/@rive-app/canvas" in text:
            offenders.append(str(path.relative_to(SITE_DIR)))
    assert not offenders, "Built site still references unpkg Rive runtime: " + ", ".join(offenders)


def main():
    assert_required_source_assets_exist()
    run_site_build()
    assert_pages_publish_shape()
    assert_local_references_exist()
    assert_manifest_icon_references_exist()
    assert_no_unpkg_rive_runtime()
    print("Static site checks passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"Static site check failed: {exc}", file=sys.stderr)
        sys.exit(1)
