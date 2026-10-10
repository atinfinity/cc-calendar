"""The Japanese docs in docs/ja/ mirror the English pages in docs/."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN = ROOT / "docs"
JA = EN / "ja"
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
    return FENCE.sub("", path.read_text(encoding="utf-8"))


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


ALL = [d / p for d in (EN, JA) for p in PAGES]


@pytest.mark.parametrize("path", ALL, ids=[str(p.relative_to(ROOT)) for p in ALL])
def test_images_resolve_from_the_page(path):
    # GitHub shows the Markdown files as they are, so the paths must work from the page too
    for src in IMAGE.findall(body(path)):
        if "://" not in src:
            assert (path.parent / src).is_file(), src
