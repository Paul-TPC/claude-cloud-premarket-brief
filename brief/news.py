"""新聞：RSS / JSON 解析、時間範圍過濾、去重、排序。只存標題和連結。"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

from .dates import TAIPEI

MAX_ITEMS = 150
SIMILARITY = 0.9  # 正規化後的標題相似度到這個值就當成同一則

SOURCE_NAMES = {"news_yahoo": "Yahoo股市", "news_udn": "經濟日報", "news_cnyes": "鉅亨網"}


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_at: datetime

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(timespec="seconds"),
        }


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def parse_rss(body: bytes, source: str) -> list[NewsItem]:
    root = ET.fromstring(body)
    items = []
    for it in root.iter("item"):
        title, link, pub = _text(it, "title"), _text(it, "link"), _text(it, "pubDate")
        if not (title and link and pub):
            continue
        items.append(NewsItem(title, source, link, parsedate_to_datetime(pub).astimezone(TAIPEI)))
    return items


def parse_cnyes(body: bytes, source: str) -> list[NewsItem]:
    data = json.loads(body)
    items = []
    for it in data["items"]["data"]:
        published = datetime.fromtimestamp(int(it["publishAt"]), TAIPEI)
        url = f"https://news.cnyes.com/news/id/{it['newsId']}"
        items.append(NewsItem(str(it["title"]).strip(), source, url, published))
    return items


_SPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """全半形統一（NFKC）、去掉所有空白。"""
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", title))


def in_range(items: list[NewsItem], start: datetime, end: datetime) -> list[NewsItem]:
    return [x for x in items if start <= x.published_at <= end]


def dedupe(items: list[NewsItem], threshold: float = SIMILARITY) -> list[NewsItem]:
    """標題正規化後相同或很像的只留最早的一則。"""
    kept: list[tuple[str, NewsItem]] = []
    for item in sorted(items, key=lambda x: x.published_at):
        norm = normalize_title(item.title)
        if any(norm == k or SequenceMatcher(None, norm, k).ratio() >= threshold for k, _ in kept):
            continue
        kept.append((norm, item))
    return [x for _, x in kept]


def finalize(items: list[NewsItem], start: datetime, end: datetime) -> list[NewsItem]:
    result = dedupe(in_range(items, start, end))
    result.sort(key=lambda x: x.published_at, reverse=True)
    return result[:MAX_ITEMS]
