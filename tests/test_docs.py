"""The Japanese docs in docs-ja/ mirror the English pages in docs/."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN = ROOT / "docs"
JA = ROOT / "docs-ja"
PAGES = sorted(p.name for p in EN.glob("*.md"))

FENCE = re.compile(r"^```.*?^```|`[^`\n]+`", re.S | re.M)
HEADING = re.compile(r"^#{1,6} .*?\{ #([\w-]+) \}\s*$", re.M)
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
LINK = re.compile(r"\]\(([\w-]+\.md(?:#[\w-]+)?|#[\w-]+)\)")


def slugify(text: str) -> str:
    """The id Python-Markdown's toc extension gives an English heading."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def body(path: Path) -> str:
    return FENCE.sub("", path.read_text())


def en_anchors(text: str) -> list[str]:
    return [slugify(m) for m in re.findall(r"^#{1,6} (.*?)\s*$", text, re.M)]


def test_every_page_is_translated():
    assert PAGES
    assert sorted(p.name for p in JA.glob("*.md")) == PAGES


@pytest.mark.parametrize("page", PAGES)
def test_headings_keep_english_anchors(page):
    assert HEADING.findall(body(JA / page)) == en_anchors(body(EN / page))


@pytest.mark.parametrize("page", PAGES)
def test_same_images_and_links(page):
    en, ja = body(EN / page), body(JA / page)
    assert IMAGE.findall(ja) == ["../" + src for src in IMAGE.findall(en)]
    assert LINK.findall(ja) == LINK.findall(en)
