"""Tests for the two clients (clients/): they share the court's rules, and each is complete enough to load."""

import json
from html.parser import HTMLParser

from hoopformer.game.replay import CLIENTS, PAGE


def test_the_wechat_client_has_the_same_court_rules_as_the_web():
    core, copy = (CLIENTS / "core" / "court.js").read_text(), (CLIENTS / "wechat" / "core" / "court.js").read_text()
    print(len(core.splitlines()), "lines of shared rules; the WeChat copy is", "the same" if copy == core else "DIFFERENT")
    assert copy == core, "run `uv run hoopformer clients` after changing clients/core/court.js"


def test_the_web_page_carries_the_court_rules_inside():
    print("page:", len(PAGE), "characters")
    assert "function createCourt(G)" in PAGE and "/*__COURT_CORE__*/" not in PAGE
    assert PAGE.index("function createCourt(G)") < PAGE.index("HoopformerCourt.createCourt(G)"), "the rules load before the page uses them"


class Tags(HTMLParser):   # opened and closed tags, to catch an unclosed one
    def __init__(self):
        super().__init__()
        self.open, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        self.open.append(tag)

    def handle_endtag(self, tag):
        if not self.open or self.open[-1] != tag:
            self.errors.append(f"</{tag}> closes {self.open[-1] if self.open else 'nothing'}")
        else:
            self.open.pop()


def test_the_wechat_client_is_a_complete_mini_program():
    app = json.loads((CLIENTS / "wechat" / "app.json").read_text())
    json.loads((CLIENTS / "wechat" / "project.config.json").read_text())
    for page in app["pages"]:
        files = {ext: CLIENTS / "wechat" / f"{page}.{ext}" for ext in ("js", "json", "wxml", "wxss")}
        print(page, {ext: path.exists() for ext, path in files.items()})
        assert all(path.exists() for path in files.values())
        json.loads(files["json"].read_text())
        tags = Tags()
        tags.feed(files["wxml"].read_text())
        assert not tags.errors and not tags.open, (tags.errors, tags.open)
    assert (CLIENTS / "wechat" / "assets" / "whistle.wav").stat().st_size > 1000
