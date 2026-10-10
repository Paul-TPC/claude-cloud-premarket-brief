import hashlib
from datetime import datetime, timedelta

from brief import news
from brief.dates import TAIPEI
from conftest import fixture_bytes


def _item(title, minutes, source="Yahoo股市"):
    t = datetime(2026, 10, 6, 14, 0, tzinfo=TAIPEI) + timedelta(minutes=minutes)
    return news.NewsItem(title, source, f"https://example.com/{minutes}", t)


def test_parse_yahoo_rss():
    items = news.parse_rss(fixture_bytes("news_yahoo.xml"), "Yahoo股市")
    assert len(items) == 50
    first = items[0]
    assert first.title.startswith("台股誰最會賺")
    assert first.url.startswith("https://tw.news.yahoo.com/")
    # Tue, 06 Oct 2026 17:23:00 GMT → 台灣時間 10/7 01:23
    assert first.to_json()["published_at"] == "2026-10-07T01:23:00+08:00"


def test_parse_udn_rss():
    items = news.parse_rss(fixture_bytes("news_udn.xml"), "經濟日報")
    assert len(items) == 20
    assert items[0].to_json() == {
        "title": "技嘉9月營收創新高",
        "source": "經濟日報",
        "url": "https://money.udn.com/money/story/5710/9798786",
        "published_at": "2026-10-07T00:24:02+08:00",
    }


def test_parse_cnyes():
    # fixture 是 limit=30 時抓的，已經刪掉 content（新聞全文）欄位
    assert b'"content"' not in fixture_bytes("news_cnyes.json")
    items = news.parse_cnyes(fixture_bytes("news_cnyes.json"), "鉅亨網")
    assert len(items) == 30
    assert items[0].url == "https://news.cnyes.com/news/id/6623158"
    # publishAt 是 Unix 秒
    assert items[0].published_at == datetime.fromtimestamp(1791301828, TAIPEI)
    assert items[0].published_at.utcoffset() == timedelta(hours=8)


def test_normalize_title():
    assert news.normalize_title("台股　大漲 ５００點") == news.normalize_title("台股大漲500點")
    assert news.normalize_title("ＡＩ 概念股") == "AI概念股"


def test_dedupe_keeps_earliest():
    items = [
        _item("台股大漲500點", 30, "經濟日報"),
        _item("台股　大漲 ５００點", 10, "Yahoo股市"),
        _item("完全不同的新聞", 20),
    ]
    got = news.dedupe(items)
    assert [(x.title, x.source) for x in got] == [("台股　大漲 ５００點", "Yahoo股市"), ("完全不同的新聞", "Yahoo股市")]


def test_dedupe_similar_titles():
    a = _item("台積電法說會釋出樂觀展望，外資連續三日買超", 5)
    b = _item("台積電法說會釋出樂觀展望，外資連續三日買超！", 6)
    c = _item("聯發科新品發表", 7)
    assert [x.title for x in news.dedupe([b, a, c])] == [a.title, c.title]


def test_in_range_boundaries():
    start = datetime(2026, 10, 6, 13, 30, tzinfo=TAIPEI)
    end = datetime(2026, 10, 7, 8, 0, tzinfo=TAIPEI)
    at_start = news.NewsItem("剛好收盤", "s", "u1", start)
    before = news.NewsItem("收盤前", "s", "u2", start - timedelta(seconds=1))
    at_end = news.NewsItem("剛好現在", "s", "u3", end)
    future = news.NewsItem("未來", "s", "u4", end + timedelta(seconds=1))
    assert [x.title for x in news.in_range([at_start, before, at_end, future], start, end)] == ["剛好收盤", "剛好現在"]


def test_finalize_sorts_newest_first_and_caps():
    assert news.MAX_ITEMS == 150
    start = datetime(2026, 10, 6, 13, 30, tzinfo=TAIPEI)
    end = datetime(2026, 10, 7, 8, 0, tzinfo=TAIPEI)
    # 用雜湊值當標題，確保彼此不相似，不會被去重
    items = [_item(hashlib.sha256(str(i).encode()).hexdigest(), i) for i in range(news.MAX_ITEMS + 20)]
    got = news.finalize(items, start, end)
    assert len(got) == news.MAX_ITEMS
    times = [x.published_at for x in got]
    assert times == sorted(times, reverse=True)
    assert got[0].published_at == items[-1].published_at


def test_finalize_on_real_feeds():
    items = (
        news.parse_rss(fixture_bytes("news_yahoo.xml"), "Yahoo股市")
        + news.parse_rss(fixture_bytes("news_udn.xml"), "經濟日報")
        + news.parse_cnyes(fixture_bytes("news_cnyes.json"), "鉅亨網")
    )
    start = datetime(2026, 10, 6, 13, 30, tzinfo=TAIPEI)
    end = datetime(2026, 10, 7, 0, 0, tzinfo=TAIPEI)
    got = news.finalize(items, start, end)
    assert 0 < len(got) <= news.MAX_ITEMS
    assert all(start <= x.published_at <= end for x in got)
    norms = [news.normalize_title(x.title) for x in got]
    assert len(norms) == len(set(norms))
