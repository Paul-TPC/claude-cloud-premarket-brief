import json

import pytest
import requests

from brief import articles
from brief.cli import main
from brief.net import Fetcher
from conftest import fake_session, fixture_bytes, fixture_json

# fixture 只有內文容器和前兩段（tools/fetch_article_fixtures.py 裁的），原始網址在檔案第一行的註解
UDN_URL = "https://money.udn.com/money/story/5710/9798786"
CALENDAR_URL = "https://money.udn.com/money/story/5607/9799374"
YAHOO_STOCK_URL = "https://tw.stock.yahoo.com/news/%E5%82%B3%E6%93%AC-115810399.html"
YAHOO_NEWS_URL = "https://tw.news.yahoo.com/%E5%B1%8F%E7%B8%A3-133154244.html"


def _text(name: str) -> str:
    return fixture_bytes(name).decode("utf-8")


def _fetcher(table: dict):
    def handler(req):
        if req.url not in table:
            return requests.ConnectionError(f"沒準備這個網址：{req.url}")
        return table[req.url]

    session, adapter = fake_session(handler)
    sleeps: list[float] = []
    return Fetcher(session, sleep=sleeps.append), adapter, sleeps


# ---- 來源判斷 ----


@pytest.mark.parametrize("url, source", [
    (UDN_URL, "經濟日報"),
    (YAHOO_STOCK_URL, "Yahoo股市"),
    (YAHOO_NEWS_URL, "Yahoo股市"),
    ("https://news.cnyes.com/news/id/6624007", "鉅亨網"),
    ("https://news.cnyes.com/news/id/6624007?exp=a", "鉅亨網"),
    ("https://udn.com/news/story/7238/9799999", None),  # 聯合新聞網，不是經濟日報
    ("https://money.udn.com/money/index", None),
    ("https://tw.stock.yahoo.com/quote/2330.TW", None),
    ("https://tw.news.yahoo.com/", None),
    ("https://news.cnyes.com/news/cat/tw_stock", None),
    ("ftp://money.udn.com/money/story/1/2", None),
    ("不是網址", None),
])
def test_detect(url, source):
    assert articles.detect(url) == source


# ---- 照真實網頁結構做的 fixture（段落是假文字）----


def test_parse_udn():
    page = articles.parse_page("經濟日報", _text("article_udn.html"))
    assert page.found
    assert page.title == "範例科技9月營收創新高"  # og:title 後面的「| 集中市場 | 證券 | 經濟日報」去掉
    # <a> 裡的字併進同一段；只有空白的 <p> 不算一段
    assert page.paragraphs == [
        "範例科技（0000）昨（6）日公布9月合併營收100.00億元，創單月歷史新高，月增10.00%，年增20.00%。"
        "這一段是測試用的假文字，和任何真實公司無關。",
        "範例科技結算，第3季合併營收300.00億元，季增5.00%。這一段也是測試用的假文字。",
    ]


def test_parse_udn_calendar_keeps_headings():
    # 行事曆的「台灣」「國際」小標是 <p><h2>台灣</h2></p>，要留著才分得出哪些是國內的事件
    page = articles.parse_page("經濟日報", _text("article_udn_calendar.html"))
    assert page.title == "10月7日重要財經行事曆"
    assert page.paragraphs == ["台灣", "主計總處發布9月消費者物價指數"]


def test_parse_yahoo_stock_skips_header_slogan():
    page = articles.parse_page("Yahoo股市", _text("article_yahoo_stock.html"))
    assert page.title == "範例電力公司：用電議題未進入政策研議"
    # <header> 裡的「加入為 Google 偏好來源」「將 Yahoo 設為首選來源…」不算內文
    assert len(page.paragraphs) == 2
    assert page.paragraphs[0].startswith("（測試通訊社台北2026年10月6日電）這是測試用的假新聞第一段")
    assert page.paragraphs[1].startswith("針對外界關注的用電議題")
    assert not any("Google" in p for p in page.paragraphs)


def test_parse_yahoo_news():
    page = articles.parse_page("Yahoo股市", _text("article_yahoo_news.html"))
    assert page.title == "範例縣政府舉辦徵才活動"
    assert page.paragraphs[0] == "▲範例縣政府在體育館舉辦徵才活動。（測試用圖說）"
    assert page.paragraphs[1].startswith("範例縣政府昨（六）日舉辦現場徵才活動")


def test_fixtures_are_trimmed():
    # 版權：fixture 只能有容器和前兩段
    for name in ("article_udn.html", "article_udn_calendar.html", "article_yahoo_stock.html", "article_yahoo_news.html"):
        assert len(fixture_bytes(name)) < 4000
    for it in fixture_json("news_cnyes_content.json")["items"]["data"]:
        assert len(articles.content_paragraphs(it["content"])) == 2


# ---- 規則（自己組的 HTML） ----


def _yahoo(body: str, header: str = "") -> str:
    return f"<html><body><article><header>{header}</header><div class='atoms'>{body}</div></article></body></html>"


def test_yahoo_slogan_outside_header_is_filtered():
    html = _yahoo(
        "<p>將 Yahoo 加入 Google 優先推薦來源</p><p>加入為 Google 偏好來源</p>"
        "<p>將 Yahoo 設為首選來源，在 Google 上查看更多我們的精彩報導</p><p>第一段內文。</p>"
    )
    assert articles.parse_page("Yahoo股市", html).paragraphs == ["第一段內文。"]


@pytest.mark.parametrize("tail", ["延伸閱讀", "【延伸閱讀】", "更多三立新聞網報導", "更多 TVBS 報導", "【看原文連結】"])
def test_yahoo_tail_is_cut(tail):
    html = _yahoo(f"<p>第一段。</p><p>第二段。</p><p>{tail}</p><p>推薦連結一</p><p>推薦連結二</p>")
    assert articles.parse_page("Yahoo股市", html).paragraphs == ["第一段。", "第二段。"]


def test_yahoo_more_in_middle_of_sentence_is_kept():
    html = _yahoo("<p>第一段。</p><p>公司表示更多細節將在法說會報導。</p>")
    assert articles.parse_page("Yahoo股市", html).paragraphs == ["第一段。", "公司表示更多細節將在法說會報導。"]


def test_only_first_article_is_used():
    html = "<article><p>主文</p></article><article><p>推薦的另一篇</p></article>"
    assert articles.parse_page("Yahoo股市", html).paragraphs == ["主文"]


def test_extract_rules():
    html = (
        "<section class='x article-body__editor'>"
        "<p>第一行<br>第二行</p>"            # <br> 分段
        "<p>  多個   空白\n換行 </p>"        # 空白合併
        "<p>沒有結束標籤<div>廣告</div>"     # div 讓 <p> 結束，div 裡不是 <p> 的字不收
        "<script>var a = '<p>不是內文</p>';</script>"
        "<section><p>巢狀 section 裡的段落</p></section>"
        "<p>&lt;跳脫&gt; &amp; 符號</p>"
        "</section><p>容器外面</p>"
    )
    page = articles.parse_page("經濟日報", html)
    assert page.paragraphs == ["第一行", "第二行", "多個 空白 換行", "沒有結束標籤", "巢狀 section 裡的段落", "<跳脫> & 符號"]


def test_container_not_found():
    page = articles.parse_page("經濟日報", "<html><head><title>錯誤</title></head><body><p>x</p></body></html>")
    assert not page.found and page.paragraphs == [] and page.title == "錯誤"


# ---- 截斷 ----


def test_truncate():
    assert articles.MAX_CHARS == 2000
    assert articles.truncate(["a" * 1000, "b" * 1000]) == (["a" * 1000, "b" * 1000], False)
    got, cut = articles.truncate(["a" * 1500, "b" * 1000])
    assert cut and got == ["a" * 1500, "b" * 500]
    got, cut = articles.truncate(["a" * 2000, "b"])
    assert cut and got == ["a" * 2000]
    got, cut = articles.truncate(["a" * 2500])
    assert cut and got == ["a" * 2000]


# ---- 鉅亨網快取 ----


def test_cnyes_content_is_escaped_html():
    raw = fixture_json("news_cnyes_content.json")["items"]["data"][0]["content"]
    assert raw.startswith("&lt;p&gt;")
    assert articles.content_paragraphs(raw) == [
        "這是測試用的假新聞第一段，數字都是編的：中位數由1.00元上修至1.10元。",
        "市場預估EPS",
    ]
    assert articles.content_paragraphs("<p>沒跳脫的</p><p>也可以</p>") == ["沒跳脫的", "也可以"]


def test_save_and_read_cnyes_cache(tmp_path):
    body = fixture_bytes("news_cnyes_content.json")
    saved, missing = articles.save_cnyes_cache(body, tmp_path / "cnyes")
    assert (saved, missing) == (2, [])
    text = (tmp_path / "cnyes" / "6624009.txt").read_text(encoding="utf-8")
    assert text.startswith("範例論壇聚焦無人機與低軌衛星\n\n面對無人機與低軌衛星的發展")
    assert "<p>" not in text and "&lt;" not in text

    f, adapter, _ = _fetcher({})
    r = articles.fetch_article("https://news.cnyes.com/news/id/6624009", f, tmp_path / "cnyes")
    assert r["ok"] and r["source"] == "鉅亨網" and r["error"] is None
    assert r["title"] == "範例論壇聚焦無人機與低軌衛星"
    assert len(r["paragraphs"]) == 2 and r["paragraphs"][1].startswith("主辦單位表示")
    assert r["chars"] == sum(len(p) for p in r["paragraphs"])
    assert adapter.requests == []  # 鉅亨網不抓網頁


def test_cnyes_missing_content(tmp_path):
    # v1 的 fixture 刪掉了 content，當成 API 沒給全文
    saved, missing = articles.save_cnyes_cache(fixture_bytes("news_cnyes.json"), tmp_path)
    assert saved == 0 and len(missing) == 30 and missing[0] == "6623158"


def test_cnyes_without_cache(tmp_path):
    f, _, _ = _fetcher({})
    r = articles.fetch_article("https://news.cnyes.com/news/id/1", f, tmp_path)
    assert not r["ok"] and "collect" in r["error"]


# ---- 抓網頁 ----


def test_fetch_article_ok():
    f, adapter, _ = _fetcher({UDN_URL: (200, fixture_bytes("article_udn.html"))})
    r = articles.fetch_article(UDN_URL, f)
    assert r == {
        "url": UDN_URL, "source": "經濟日報", "title": "範例科技9月營收創新高", "ok": True, "error": None,
        "paragraphs": r["paragraphs"], "chars": sum(len(p) for p in r["paragraphs"]), "truncated": False,
    }
    assert len(r["paragraphs"]) == 2
    assert len(adapter.requests) == 1


def test_fetch_article_truncated():
    html = "<article><p>" + "字" * 1500 + "</p><p>" + "多" * 1500 + "</p></article>"
    f, _, _ = _fetcher({YAHOO_NEWS_URL: (200, html.encode())})
    r = articles.fetch_article(YAHOO_NEWS_URL, f)
    assert r["ok"] and r["truncated"] and r["chars"] == 2000


def test_fetch_article_failures():
    f, adapter, _ = _fetcher({
        UDN_URL: (404, b"not found"),
        YAHOO_STOCK_URL: (200, b"<html><body><p>no article</p></body></html>"),
        YAHOO_NEWS_URL: (200, b"<article><header><p>only header</p></header></article>"),
    })
    assert articles.fetch_article(UDN_URL, f)["error"] == "HTTP 404"
    assert articles.fetch_article(YAHOO_STOCK_URL, f)["error"] == "找不到內文容器"
    assert articles.fetch_article(YAHOO_NEWS_URL, f)["error"] == "內文是空的"
    r = articles.fetch_article("https://www.example.com/news/1", f)
    assert r == {"url": "https://www.example.com/news/1", "source": None, "title": None, "ok": False,
                 "error": "不支援的網站", "paragraphs": [], "chars": 0, "truncated": False}
    assert "example.com" not in [requests.utils.urlparse(x.url).hostname for x in adapter.requests]
    # 404 不重試；連線失敗才重試
    assert [x.url for x in adapter.requests].count(UDN_URL) == 1


def test_run_outputs_json_and_exit_codes(capsys, tmp_path):
    table = {
        UDN_URL: (200, fixture_bytes("article_udn.html")),
        YAHOO_STOCK_URL: (200, fixture_bytes("article_yahoo_stock.html")),
        YAHOO_NEWS_URL: (200, fixture_bytes("article_yahoo_news.html")),
    }
    f, adapter, sleeps = _fetcher(table)
    code = articles.run([UDN_URL, YAHOO_STOCK_URL, YAHOO_NEWS_URL, UDN_URL], fetcher=f, cache_dir=tmp_path)
    out = json.loads(capsys.readouterr().out)
    assert code == articles.EXIT_OK
    assert [x["url"] for x in out] == [UDN_URL, YAHOO_STOCK_URL, YAHOO_NEWS_URL, UDN_URL]
    assert all(x["ok"] for x in out)
    assert len(adapter.requests) == 3  # 重複的網址只抓一次
    assert sleeps and all(s > 0 for s in sleeps)  # tw.stock.yahoo.com 和 tw.news.yahoo.com 同網域，要間隔

    f, _, _ = _fetcher(table)
    code = articles.run([UDN_URL, "https://www.example.com/x"], fetcher=f, cache_dir=tmp_path)
    out = json.loads(capsys.readouterr().out)
    assert code == articles.EXIT_PARTIAL
    assert [x["ok"] for x in out] == [True, False]


def test_cli_articles_without_urls_exits_1(capsys):
    with pytest.raises(SystemExit) as e:
        main(["articles"])
    assert e.value.code == 1
