"""python -m brief articles：抓指定新聞的內文，輸出 JSON 到標準輸出。內文不寫進 repo。"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .net import Fetcher, log, redact

MAX_CHARS = 2000  # 每篇最多幾個字，超過就截斷
CNYES_CACHE = Path(".cache") / "cnyes"  # collect 把鉅亨網列表 API 的 content 存在這裡

EXIT_OK, EXIT_PARTIAL = 0, 2  # 參數錯誤的 1 由 argparse 處理

_SPACE_RE = re.compile(r"\s+")
_CNYES_PATH_RE = re.compile(r"^/news/id/(\d+)")
_CHARSET_RE = re.compile(r"charset=[\"']?([\w-]+)", re.I)

# <p> 遇到這些區塊標籤就算結束（HTML 允許 <p> 不寫結束標籤）
_BLOCK_TAGS = {"address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure", "footer", "form",
               "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section",
               "table", "ul"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_BR = "\x00"  # <br> 的記號；原始碼裡的換行只是空白，不分段


@dataclass
class Page:
    title: str | None
    found: bool  # 有沒有找到內文容器
    paragraphs: list[str]


class _Extractor(HTMLParser):
    """找第一個符合 match 的容器，收集容器裡每個 <p> 的文字；<br> 當成分段。

    match 是 None 時整份 HTML 都算容器（鉅亨網的 content 是 HTML 片段）。
    headings=True 時容器裡的 <h1>～<h6> 也算一段（經濟日報行事曆的「台灣」「國際」小標）。
    exclude 裡的標籤（例如 Yahoo 的 <header>）整塊跳過。另外記下 og:title 和 <title>。
    """

    def __init__(self, match: Callable[[str, dict], bool] | None, *, headings: bool = False,
                 exclude: frozenset[str] = frozenset()) -> None:
        super().__init__(convert_charrefs=True)
        self.match = match
        self.headings = headings
        self.exclude = exclude
        self.container: str | None = None  # 容器的標籤名稱
        self.depth = 1 if match is None else 0  # 容器裡同名標籤的層數，0 代表不在容器裡
        self.found = match is None
        self.done = False
        self.skip = 0
        self.ex_tag: str | None = None  # 正在跳過的 exclude 標籤
        self.ex_depth = 0
        self.cur: list[str] | None = None  # 正在收的段落
        self.paragraphs: list[str] = []
        self.og_title: str | None = None
        self._title: list[str] | None = None
        self.title: str | None = None

    @property
    def inside(self) -> bool:
        return self.depth > 0 and not self.done and self.ex_tag is None

    def _flush(self) -> None:
        if self.cur is None:
            return
        for line in "".join(self.cur).split(_BR):
            text = _SPACE_RE.sub(" ", line).strip()
            if text:
                self.paragraphs.append(text)
        self.cur = None

    def _starts_paragraph(self, tag: str) -> bool:
        return tag == "p" or (self.headings and tag in _HEADING_TAGS)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta" and a.get("property") == "og:title" and self.og_title is None:
            self.og_title = a.get("content", "").strip() or None
        if tag == "title" and self.title is None:
            self._title = []
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if self.done:
            return
        if self.depth == 0:
            if self.match is not None and self.match(tag, a):
                self.container, self.depth, self.found = tag, 1, True
            return
        if tag == self.container:
            self.depth += 1
        if self.ex_tag is not None:
            self.ex_depth += tag == self.ex_tag
            return
        if tag in self.exclude:
            self._flush()
            self.ex_tag, self.ex_depth = tag, 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if self._starts_paragraph(tag):
            self.cur = []
        elif tag == "br" and self.cur is not None:
            self.cur.append(_BR)

    def handle_endtag(self, tag):
        if tag == "title" and self._title is not None:
            self.title = _SPACE_RE.sub(" ", "".join(self._title)).strip() or None
            self._title = None
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.done or self.depth == 0:
            return
        if self.ex_tag is not None:
            if tag == self.ex_tag:
                self.ex_depth -= 1
                if self.ex_depth == 0:
                    self.ex_tag = None
            if tag != self.container:
                return
        elif tag == "p" or tag in _BLOCK_TAGS:
            self._flush()
        if tag == self.container:
            self.depth -= 1
            if self.depth == 0:
                self._flush()
                self.done = True

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        if self.skip or not self.inside or self.cur is None:
            return
        self.cur.append(data)

    def close(self):
        super().close()
        self._flush()


def extract(markup: str, match: Callable[[str, dict], bool] | None, **kwargs) -> Page:
    p = _Extractor(match, **kwargs)
    p.feed(markup)
    p.close()
    return Page(title=p.og_title or p.title, found=p.found, paragraphs=p.paragraphs)


def _udn_container(tag: str, a: dict) -> bool:
    return tag == "section" and "article-body__editor" in a.get("class", "").split()


def _yahoo_container(tag: str, a: dict) -> bool:
    return tag == "article"


# Yahoo：開頭「把 Yahoo 設成 Google 偏好來源」的標語、結尾的延伸閱讀。
# 標語在 <article> 的 <header> 裡，已經整塊跳過；文字比對是備案（2026-10-07 雲端看到的字樣和 SPEC 寫的不同）。
_YAHOO_SLOGAN_RE = re.compile(r"Google\s*(?:上的)?\s*(?:偏好|優先推薦|首選)來源|設為首選來源")
_YAHOO_TAIL_RE = re.compile(r"^[【〔\[〈《]?\s*(延伸閱讀|更多.{0,20}?報導|看原文)")  # 看原文：2026-10-07 雲端看到「【看原文連結】」


def clean_yahoo(paragraphs: list[str]) -> list[str]:
    out = []
    for p in paragraphs:
        if _YAHOO_TAIL_RE.match(p):
            break  # 從這裡開始都是推薦連結
        if _YAHOO_SLOGAN_RE.search(p):
            continue
        out.append(p)
    return out


def truncate(paragraphs: list[str], limit: int = MAX_CHARS) -> tuple[list[str], bool]:
    out, total = [], 0
    for p in paragraphs:
        if total + len(p) > limit:
            rest = limit - total
            if rest > 0:
                out.append(p[:rest])
            return out, True
        out.append(p)
        total += len(p)
    return out, False


# ---- 來源判斷 ----

UDN, YAHOO, CNYES = "經濟日報", "Yahoo股市", "鉅亨網"


def detect(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    host, path = (parts.hostname or "").lower(), parts.path
    if host == "money.udn.com" and path.startswith("/money/story/"):
        return UDN
    if (host == "tw.stock.yahoo.com" and path.startswith("/news/")) or (host == "tw.news.yahoo.com" and len(path) > 1):
        return YAHOO
    if host == "news.cnyes.com" and _CNYES_PATH_RE.match(path):
        return CNYES
    return None


def _decode(resp) -> str:
    m = _CHARSET_RE.search(resp.headers.get("Content-Type", ""))
    charset = m.group(1) if m else "utf-8"
    try:
        return resp.content.decode(charset, errors="replace")
    except LookupError:
        return resp.content.decode("utf-8", errors="replace")


def parse_page(source: str, markup: str) -> Page:
    """經濟日報、Yahoo 的網頁 → 標題和內文段落（已經濾掉標語、延伸閱讀）。"""
    if source == UDN:
        page = extract(markup, _udn_container, headings=True)
        if page.title:  # og:title 是「標題 | 市場焦點 | 證券 | 經濟日報」
            page.title = page.title.split(" | ")[0].strip() or page.title
        return page
    page = extract(markup, _yahoo_container, exclude=frozenset({"header"}))
    page.paragraphs = clean_yahoo(page.paragraphs)
    return page


# ---- 鉅亨網：collect 時存的快取 ----
# 格式：第一行標題，第二行空白，之後一段一行。


def content_paragraphs(content: str) -> list[str]:
    """鉅亨網列表 API 的 content → 段落。content 是跳脫過的 HTML（`&lt;p&gt;…`），先還原再取 <p>。"""
    if "<" not in content and "&lt;" in content:
        content = html.unescape(content)
    return extract(content, None).paragraphs


def save_cnyes_cache(body: bytes, cache_dir: Path) -> tuple[int, list[str]]:
    """把鉅亨網列表 API 每則的 content 去 HTML 後存成 <newsId>.txt。回傳 (存了幾則, 沒有 content 的 newsId)。"""
    data = json.loads(body)
    cache_dir.mkdir(parents=True, exist_ok=True)
    saved, missing = 0, []
    for it in data["items"]["data"]:
        news_id = str(it["newsId"])
        paragraphs = content_paragraphs(it.get("content") or "")
        if not paragraphs:
            missing.append(news_id)
            continue
        title = _SPACE_RE.sub(" ", str(it.get("title") or "")).strip()
        (cache_dir / f"{news_id}.txt").write_text(title + "\n\n" + "\n".join(paragraphs) + "\n", encoding="utf-8")
        saved += 1
    return saved, missing


def read_cnyes_cache(news_id: str, cache_dir: Path) -> Page | None:
    path = cache_dir / f"{news_id}.txt"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").split("\n")
    title = lines[0].strip() or None
    return Page(title=title, found=True, paragraphs=[x for x in (s.strip() for s in lines[2:]) if x])


# ---- 主流程 ----


def _failed(url: str, error: str | None = None) -> dict:
    return {"url": url, "source": detect(url), "title": None, "ok": False, "error": error,
            "paragraphs": [], "chars": 0, "truncated": False}


def fetch_article(url: str, fetcher: Fetcher, cache_dir: Path = CNYES_CACHE) -> dict:
    result = _failed(url)
    source = result["source"]
    if source is None:
        result["error"] = "不支援的網站"
        return result
    if source == CNYES:
        news_id = _CNYES_PATH_RE.match(urlsplit(url).path).group(1)
        page = read_cnyes_cache(news_id, cache_dir)
        if page is None:
            result["error"] = f"沒有快取 {cache_dir / (news_id + '.txt')}（鉅亨網的內文是 collect 時存的，要先跑 collect）"
            return result
    else:
        r = fetcher.get(url)
        if not r.ok:
            result["error"] = redact(r.error)
            return result
        try:
            page = parse_page(source, _decode(r.response))
        except Exception as e:  # 解析失敗只影響這一篇
            result["error"] = redact(f"解析失敗：{type(e).__name__}: {e}")
            return result
        if not page.found:
            result["title"] = page.title
            result["error"] = "找不到內文容器"
            return result
    result["title"] = page.title
    if not page.paragraphs:
        result["error"] = "內文是空的"
        return result
    paragraphs, truncated = truncate(page.paragraphs)
    result.update(ok=True, paragraphs=paragraphs, chars=sum(len(p) for p in paragraphs), truncated=truncated)
    return result


def run(urls: list[str], *, fetcher: Fetcher | None = None, cache_dir: Path = CNYES_CACHE) -> int:
    fetcher = fetcher or Fetcher()
    results, seen = [], {}
    for url in urls:
        if url not in seen:  # 同一個網址只抓一次
            try:
                seen[url] = fetch_article(url, fetcher, cache_dir)
            except Exception as e:  # 一篇出錯不中止其他篇
                seen[url] = _failed(url, redact(f"{type(e).__name__}: {e}"))
            if not seen[url]["ok"]:
                log(f"articles 失敗：{seen[url]['error']}（{url}）")
        results.append(seen[url])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return EXIT_OK if all(r["ok"] for r in results) else EXIT_PARTIAL
