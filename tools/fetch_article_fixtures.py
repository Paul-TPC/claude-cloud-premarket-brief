"""v2 articles 的測試 fixture（開發用，不是每天跑的）。

內文有版權，repo 只放「內文容器和前兩段」，不放整頁、不放全文。分兩步：

1. fetch：抓原始網頁存到 repo 以外的目錄（請求規矩和 collect 一樣）
   python tools/fetch_article_fixtures.py fetch <repo 外的目錄> 檔名=網址 ... [cnyes]
   `cnyes` 代表鉅亨網列表 API（SPEC 第 5 節的 news_cnyes）。
2. trim：從那個目錄裁出 fixture，寫到 tests/fixtures/
   python tools/fetch_article_fixtures.py trim <repo 外的目錄> 檔名 ... [cnyes]
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brief import articles, sources  # noqa: E402
from brief.net import Fetcher, log  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
KEEP = 2  # 留前幾段
CNYES_ITEMS = 2  # 鉅亨網列表留幾則


def _outside_repo(path: Path) -> Path:
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise SystemExit(f"原始網頁有全文，不能存在 repo 裡：{path}")
    return path


def fetch(raw_dir: Path, specs: list[str]) -> int:
    raw_dir = _outside_repo(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f, failed = Fetcher(), 0
    for spec in specs:
        name, url = ("cnyes", sources.NEWS_CNYES) if spec == "cnyes" else spec.split("=", 1)
        r = f.get(url)
        if not r.ok:
            log(f"{name}：{r.error}")
            failed += 1
            continue
        (raw_dir / f"{name}.raw").write_bytes(r.response.content)
        (raw_dir / f"{name}.url").write_text(url + "\n", encoding="utf-8")
        ctype = r.response.headers.get("Content-Type", "")
        print(f"{name}\t{r.status}\t{len(r.response.content)} bytes\t{r.elapsed_ms} ms\t{ctype}\t{r.response.url}")
    return 1 if failed else 0


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Spans(HTMLParser):
    """記下容器開始標籤、容器裡每個 <p> 的原始位置（字元位移）和它在容器裡的上層標籤。"""

    def __init__(self, text: str, match) -> None:
        super().__init__(convert_charrefs=True)
        self.lines = [0]
        for m in re.finditer("\n", text):
            self.lines.append(m.end())
        self.match = match
        self.container = None
        self.start_tag = None
        self.depth = 0
        self.done = False
        self.stack: list[tuple[int, str, str]] = []  # (編號, 標籤, 原始開始標籤)，不含容器本身
        self.serial = 0
        self.p_open: tuple[int, list] | None = None
        self.paragraphs: list[tuple[list, int, int]] = []  # (上層標籤, 開始, 結束)

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        a = {k: (v or "") for k, v in attrs}
        if self.depth == 0:
            if self.match(tag, a):
                self.container, self.depth, self.start_tag = tag, 1, self.get_starttag_text()
            return
        if tag == self.container:
            self.depth += 1
        if tag == "p":
            self.p_open = (self._pos(), list(self.stack))
        if tag not in _VOID:
            self.serial += 1
            self.stack.append((self.serial, tag, self.get_starttag_text()))

    def handle_endtag(self, tag):
        if self.done or self.depth == 0 or tag in _VOID:
            return
        if tag == self.container and self.depth == 1:
            self.done = True
            return
        if tag == self.container:
            self.depth -= 1
        if tag == "p" and self.p_open is not None:
            start, ancestors = self.p_open
            self.paragraphs.append((ancestors, start, self._pos() + len("</p>")))
            self.p_open = None
        if any(t == tag for _, t, _ in self.stack):
            while self.stack and self.stack.pop()[1] != tag:
                pass


def _skeleton(text: str, chosen: list[tuple[list, int, int]]) -> str:
    """只留選到的 <p> 和它們的上層標籤（開始標籤照原樣），其他內容都不留。"""
    out: list[str] = []
    opened: list[tuple[int, str, str]] = []
    for ancestors, s, e in chosen:
        common = 0
        while common < min(len(opened), len(ancestors)) and opened[common][0] == ancestors[common][0]:
            common += 1
        for _, tag, _ in reversed(opened[common:]):
            out.append(f"</{tag}>")
        for _, _, raw in ancestors[common:]:
            out.append(raw)
        opened = list(ancestors)
        out.append(text[s:e])
    for _, tag, _ in reversed(opened):
        out.append(f"</{tag}>")
    return "\n".join(out)


def _meta(text: str) -> str:
    """og:title 和 <title>（不是內文，parse_page 要用來取標題）。"""
    out = []
    m = re.search(r"<meta[^>]+property=[\"']og:title[\"'][^>]*>", text)
    if m:
        out.append(m.group(0))
    m = re.search(r"<title[^>]*>.*?</title>", text, re.S)
    if m:
        out.append(m.group(0))
    return "\n".join(out)


def trim_page(name: str, raw_dir: Path) -> None:
    url = (raw_dir / f"{name}.url").read_text(encoding="utf-8").strip()
    source = articles.detect(url)
    text = (raw_dir / f"{name}.raw").read_bytes().decode("utf-8")
    match = articles._udn_container if source == articles.UDN else articles._yahoo_container
    spans = _Spans(text, match)
    spans.feed(text)
    if spans.start_tag is None:
        raise SystemExit(f"{name}：找不到內文容器")
    # 一個 <p> 一個 <p> 加，直到 parse_page 的結果有 KEEP 段（Yahoo 標語這類會被濾掉的段落也留著）
    got: list[str] = []
    for n in range(1, len(spans.paragraphs) + 1):
        body = _skeleton(text, spans.paragraphs[:n])
        html = (f"<html><head>\n{_meta(text)}\n</head><body>\n{spans.start_tag}\n{body}\n"
                f"</{spans.container}>\n</body></html>\n")
        got = articles.parse_page(source, html).paragraphs
        if len(got) >= KEEP:
            break
    if len(got) > KEEP:
        raise SystemExit(f"{name}：一個 <p> 裡就超過 {KEEP} 段（有 <br>），要另外處理")
    note = f"<!-- 測試用：只留內文容器和前 {KEEP} 段，不是整頁。原始網址 {url} -->\n"
    (FIXTURES / f"{name}.html").write_text(note + html, encoding="utf-8")
    print(f"{name}.html\t{n} 個 <p>\t{got}")


def _first_paragraphs(content: str) -> str:
    """鉅亨網 content 只留前 KEEP 個有字的 <p>，再照原本的樣子跳脫回去（API 回的是 `&lt;p&gt;…`）。"""
    escaped = "<" not in content and "&lt;" in content
    text = "<div>" + (html_lib.unescape(content) if escaped else content) + "</div>"
    spans = _Spans(text, lambda tag, a: tag == "div")
    spans.feed(text)
    kept, out = 0, []
    for _, s, e in spans.paragraphs:
        out.append(text[s:e])
        kept += bool(articles.content_paragraphs(text[s:e]))
        if kept >= KEEP:
            break
    joined = "\n\n".join(out)
    return html_lib.escape(joined, quote=True) if escaped else joined


def trim_cnyes(raw_dir: Path) -> None:
    data = json.loads((raw_dir / "cnyes.raw").read_bytes())
    items = []
    for it in data["items"]["data"][:CNYES_ITEMS]:
        items.append({"newsId": it["newsId"], "title": it["title"], "publishAt": it["publishAt"],
                      "content": _first_paragraphs(it.get("content") or "")})
    out = {"_note": f"測試用：只留前 {CNYES_ITEMS} 則，content 只留前 {KEEP} 段", "items": {"data": items}}
    path = FIXTURES / "news_cnyes_content.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{path.name}\t{[articles.content_paragraphs(x['content']) for x in items]}")


def trim(raw_dir: Path, names: list[str]) -> int:
    raw_dir = _outside_repo(raw_dir)
    for name in names:
        trim_cnyes(raw_dir) if name == "cnyes" else trim_page(name, raw_dir)
    return 0


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[1] not in ("fetch", "trim"):
        print(__doc__)
        return 1
    cmd, raw_dir, rest = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
    return fetch(raw_dir, rest) if cmd == "fetch" else trim(raw_dir, rest)


if __name__ == "__main__":
    raise SystemExit(main())
