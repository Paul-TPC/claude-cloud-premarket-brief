# 規格：台股盤前資訊整理（v1.1）

最後更新：2026-10-07

## 1. 目的

每個交易日早上 8 點多，把**前一個交易日**的盤後資料和**前一交易日收盤到現在**的新聞整理好，送到 Telegram。讓投資人不用每天自己去各個網站收集。

只做資訊收集和整理，不做投資建議。

## 2. 範圍

| 做 | 不做（第一版） |
|---|---|
| 上市大盤、成交量值、三大法人、融資融券、類股指數、觀察清單 ETF、ETF 除息預告、新聞標題 | 美股、上櫃（櫃買）、個股分析、新聞全文、技術指標、任何買賣建議 |

觀察清單（放在 `config.toml`，之後可以改）：

| 代號 | 名稱 |
|---|---|
| 0050 | 元大台灣50 |
| 006208 | 富邦台50 |
| 0056 | 元大高股息 |
| 00878 | 國泰永續高股息 |
| 00919 | 群益台灣精選高息 |

## 3. 指令

套件名稱 `brief`，Python 3.11 以上，依賴只有 `requests`（其他用標準函式庫，設定檔用 `tomllib`）。

### `python -m brief check`

逐一請求第 5 節的每個來源和 `https://api.telegram.org`（不帶 token，只看連不連得到），印出：來源名稱、HTTP 狀態碼、耗時、錯誤訊息。證交所的擋頁（狀態碼 200 或 307）也算連不到。全部連得到回傳 0，否則回傳 2。

### `python -m brief collect [--date YYYY-MM-DD] [--out data/]`

- `--date` 是**報告日**，預設今天（Asia/Taipei）。
- **資料日** = 報告日之前最近的一個交易日（第 4 節）。
- 輸出 `data/<報告日>.json`（第 6 節）。
- 結束碼：
  - `0`：全部來源成功
  - `2`：部分來源失敗（包括 MI_INDEX 裡某一個表解析失敗），JSON 仍然產生，失敗的記在 `sources`
  - `3`：報告日休市，JSON 只有日期欄位和 `market_open_today: false`
  - `1`：其他錯誤（例如連交易日都判斷不出來）

### `python -m brief send <file.md> [--dry-run]`

- 從環境變數讀 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，用 `sendMessage` 送出，`parse_mode=HTML`，關閉連結預覽。
- 報告檔用簡化的 Markdown：只支援 `**粗體**` 和 `[文字](網址)`。程式負責轉成 Telegram HTML，其餘文字的 `&`、`<`、`>` 要跳脫。
- 超過 4,096 字時以段落為單位拆成多則依序送出。
- `--dry-run`：只印出轉換後的內容和拆成幾則，不送出、不需要環境變數。
- 環境變數沒設時回傳 1，並印出「缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID」（不印出任何值）。

## 4. 交易日判斷

- 來源：證交所開休市日期 `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json`，欄位是「日期」「名稱」「說明」，日期是西元（`2026-10-09`），`stat` 是小寫 `ok`。
- 週六、週日休市；清單上的日期休市。
- 清單裡不一定每一列都是休市日（可能有「最後交易日」「開始交易日」之類的說明列），要讀「名稱」「說明」判斷。判斷不了的情況記進 `docs/PITFALLS.md`。
- 抓不到清單時只用週末判斷，並在 JSON 記 `holiday_source: "weekend_only"`。
- 已知：**2026-10-09（五）國慶日補假，休市**。

## 5. 資料來源

第一版的來源是 2026-10-07 凌晨在台灣網路實測過的（資料日 2026-10-06）；v1.1 新換的開休市日期、除權息預告、MI_INDEX `ALLBUT0999` 是 2026-10-07 03:41 在雲端機器抓的。**雲端機器在國外，要用 `check` 重新確認連不連得到**。

| 名稱 | 網址 | 用途 | 已知狀況 |
|---|---|---|---|
| `twse_holiday` | `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json` | 開休市日期 | 西元日期；`stat` 是小寫 `ok`；回應裡的 `date` 是當年 1 月 1 日（`20260101`），不是查詢日；只有當年的日期 |
| `twse_index` | `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json` | 加權指數、類股指數、成交金額、漲跌家數、觀察清單 ETF 的收盤價、漲跌、成交量 | 一個請求就有全部，取哪些表見 5.2；約 250 KB |
| `twse_institutional` | `https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=YYYYMMDD&response=json` | 三大法人買賣金額 | 單位：元 |
| `twse_margin` | `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=YYYYMMDD&selectType=MS&response=json` | 融資融券 | 單位混用：「交易單位」和「仟元」 |
| `twse_etf_institutional` | `https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL&response=json` | 觀察清單 ETF 的法人買賣超 | `ALL` 回傳約 2 萬列，可以找能縮小範圍的 `selectType`；證券名稱後面有空白要去掉；單位：股 |
| `twse_ex_dividend` | `https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json` | 除權息預告 | 日期是民國年（`115年10月22日`）；清單裡也有已經過去的日期；只列觀察清單、報告日起 14 天內；「現金股利」還沒公告時是 HTML（`<p style= text-align:center;>待公告實際收益分配金額</p>`），有公告時是 `0.12000000` |
| `news_yahoo` | `https://tw.stock.yahoo.com/rss?category=tw-market` | 新聞 | RSS，約 50 則 |
| `news_udn` | `https://money.udn.com/rssfeed/news/1001/5590?ch=money` | 新聞 | RSS，約 20 則 |
| `news_cnyes` | `https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=100` | 新聞 | 非官方 JSON，可能改版；`publishAt` 是 Unix 秒；每則帶 `content`（全文），程式不取；`limit=100` 實際可能只回 30 則（見 PITFALLS） |

證交所一共 6 個請求，全部在 `www.twse.com.tw`。

### 5.1 類股清單

MI_INDEX 表 0 裡名稱以「類指數」結尾的列，**只取下面 32 個產業類別**。不取合計類（水泥窯製類、塑膠化工類、機電類、化學生技醫療類、電子工業類），也不取槓桿、反向指數（電子類兩倍槓桿指數、電子類反向指數）：

水泥、食品、塑膠、紡織纖維、電機機械、電器電纜、化學、生技醫療、玻璃陶瓷、造紙、鋼鐵、橡膠、汽車、半導體、電腦及週邊設備、光電、通信網路、電子零組件、電子通路、資訊服務、其他電子、建材營造、航運、觀光餐旅、金融保險、貿易百貨、油電燃氣、綠能環保、數位雲端、運動休閒、居家生活、其他

（表裡的名稱是「半導體類指數」這種形式；JSON 的 `name` 存「半導體」。）

### 5.2 MI_INDEX（`type=ALLBUT0999`）取哪些表

回傳 10 個表。用標題（不含前面的日期）找表，不靠順序；找不到就算這部分失敗。2026-10-06 的順序如下：

| 表 | 標題 | 取什麼 |
|---|---|---|
| 0 | `115年10月06日 價格指數(臺灣證券交易所)` | 「發行量加權股價指數」和 5.1 的類股。「漲跌(+/-)」欄夾 HTML（`<p style ='color:red'>+</p>`），要清掉；**下跌時「漲跌百分比」本身就帶負號（`-0.83`），「漲跌」欄又有一個 `-`，兩個不要相乘** |
| 6 | `115年10月06日 大盤統計資訊` | 「總計(1~15)」列的「成交金額(元)」當成交金額（和以前用的 FMTQIK 成交金額相同，2026-10-06 都是 1,026,204,771,139） |
| 7 | `漲跌證券數合計` | 「股票」欄的「上漲(漲停)」「下跌(跌停)」家數。格式是 `462(10)`，括號裡是漲停、跌停家數，不取。「整體市場」欄含權證等，不取 |
| 8 | `115年10月06日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))` | 觀察清單 ETF 的「收盤價」「漲跌(+/-)」「漲跌價差」「成交股數」。「漲跌(+/-)」的 HTML 和表 0 不同：`<p style= color:red>+</p>`、`<p style= color:green>-</p>`、平盤 `<p> </p>`、不比價 `<p>X</p>`（例如除權息當天，漲跌價差是 `0.00`）；**漲跌價差不帶正負號**，正負號只看「漲跌(+/-)」；沒成交時收盤價是 `--` |

每個表分開解析：某一個表解析失敗時，只有對應的欄位是 `null`，`twse_index` 記成失敗（結束碼 2），其他表照常。

**不用** `openapi.twse.com.tw`：行情類端點（`STOCK_DAY_ALL`、`MI_INDEX`）沒有日期參數，而且會延遲（2026-10-07 凌晨 1 點多還是 10/5 的資料，網站端點已經有 10/6）；開休市日期、除權息預告在雲端機器常回 HTTP 200 的擋頁。全部改用 `www.twse.com.tw` 的 `rwd` 端點。

### 抓資料的規矩

- 每個請求逾時 15 秒，失敗重試 1 次。
- 同一個網域的請求之間至少間隔 3 秒（證交所對頻繁請求會暫時封鎖 IP，這是常見說法，沒有官方文件；被擋就記進 PITFALLS）。
- User-Agent 用一般瀏覽器字串。
- 任何一個來源失敗都不中止，在 `sources` 記下錯誤，結束碼 2。
- 證交所回應的 `stat` 不是 `OK`（不分大小寫，開休市日期是小寫 `ok`；例如「很抱歉，沒有符合條件的資料!」）也算失敗。
- 證交所的安全機制擋頁（「因為安全性考量，您所執行的頁面無法呈現」，狀態碼可能是 200 或 307）算失敗，照上面的規定重試。

### 新聞

- 時間範圍：資料日 13:30 到執行當下（Asia/Taipei）。
- 欄位：標題、來源、網址、發布時間。只存標題和連結，不抓全文。
- 去重：標題正規化（去空白、全半形統一）後相同，或相似度很高的，只留一則（留最早的）。
- 依發布時間由新到舊排序，最多 150 則。

## 6. JSON 格式

每個數字欄位都附一個 `display` 字串，是報告直接照抄的格式。AI 不做任何換算。

| 種類 | `display` 格式 | 例子 |
|---|---|---|
| 指數 | 千分位、兩位小數 | `49,822.55` |
| 漲跌 | 帶正負號；指數兩位小數，百分比兩位小數加 % | `+110.51`、`+0.22%` |
| 金額 | 換成億元，一位小數；買賣超、增減帶正負號，餘額、成交金額不帶 | `-66.6 億`、`10,262.0 億` |
| 張數 | 股數除以 1,000；融券本來就是張（交易單位）不用除；千分位；買賣超、增減帶正負號 | `-15,986 張`、`214,529 張` |
| 家數 | 千分位，不帶正負號 | `462 家`、`1,083 家` |
| ETF 收盤價 | 照證交所原樣（兩位小數） | `116.50` |
| ETF 漲跌幅 | 漲跌價差（正負號看「漲跌(+/-)」）÷ 前一日收盤（收盤 − 漲跌價差）× 100，兩位小數，帶正負號 | `+0.47%` |

所有四捨五入都用「四捨五入」（`ROUND_HALF_UP`），不要用 Python 內建 `round()` 的銀行家捨入。

融資餘額用「融資金額(仟元)」那一列換成億元；融券餘額用「融券(交易單位)」那一列。增減 = 今日餘額 − 前日餘額。

ETF 的外資 =「外陸資買賣超股數(不含外資自營商)」（外資自營商已經算在自營商裡，不再加）；投信 =「投信買賣超股數」。

```json
{
  "report_date": "2026-10-08",
  "data_date": "2026-10-07",
  "market_open_today": true,
  "holiday_source": "twse",
  "generated_at": "2026-10-08T08:07:31+08:00",
  "sources": [
    {"name": "twse_index", "url": "...", "ok": true, "error": null, "elapsed_ms": 820}
  ],
  "warnings": ["0056 漲跌不是一般格式：漲跌(+/-) 'X'、漲跌價差 '0.00'"],
  "index": {
    "taiex": {"close": 49822.55, "change": 110.51, "change_pct": 0.22,
              "display": {"close": "49,822.55", "change": "+110.51", "change_pct": "+0.22%"}},
    "turnover": {"value_twd": 1026204771139, "display": {"value": "10,262.0 億"}},
    "breadth": {"up": 462, "down": 519, "display": {"up": "462 家", "down": "519 家"}}
  },
  "sectors": [
    {"name": "半導體", "close": 0, "change_pct": 0, "display": {"close": "...", "change_pct": "..."}}
  ],
  "institutional": {
    "foreign": {"net_twd": -6657341610, "display": "-66.6 億"},
    "investment_trust": {"net_twd": -14264918768, "display": "-142.6 億"},
    "dealer": {"net_twd": 1721212199, "display": "+17.2 億"},
    "total": {"net_twd": -19201048179, "display": "-192.0 億"}
  },
  "margin": {"financing_balance_k_twd": 637657044, "financing_change_k_twd": 4305323, "short_balance_lots": 214529, "short_change_lots": -3929,
             "display": {"financing_balance": "6,376.6 億", "financing_change": "+43.1 億", "short_balance": "214,529 張", "short_change": "-3,929 張"}},
  "etfs": [
    {"code": "0050", "name": "元大台灣50", "close": 116.50, "change": 0.55, "change_pct": 0.47, "volume_lots": 70946,
     "foreign_net_lots": -15986, "trust_net_lots": -40, "dealer_net_lots": -568,
     "display": {"close": "116.50", "change_pct": "+0.47%", "volume": "70,946 張",
                 "foreign_net": "-15,986 張", "trust_net": "-40 張", "dealer_net": "-568 張"}}
  ],
  "ex_dividend": [
    {"code": "0056", "name": "元大高股息", "date": "2026-10-22", "type": "息", "cash_dividend": null, "display": {"cash_dividend": "尚未公告"}}
  ],
  "news": [
    {"title": "...", "source": "Yahoo股市", "url": "...", "published_at": "2026-10-07T17:05:00+08:00"}
  ]
}
```

- 日期一律西元 `YYYY-MM-DD`，時間帶 `+08:00`。
- `sectors` 依漲跌幅排序，全部列出。
- 三大法人：外資 =「外資及陸資(不含外資自營商)」；自營商 =「自營商(自行買賣)」+「自營商(避險)」（已經包含外資自營商，所以外資不再加「外資自營商」）；合計直接取「合計」列，三項加起來會等於合計。
- `taiex`、`turnover`、`breadth`、`institutional`、`margin`、0050 的價格和法人買賣超是 2026-10-06 的實際值，可以拿來寫測試；`sectors`、`news`、`warnings` 和標 `...` 的只是格式示意。
- `index.breadth`：MI_INDEX 表 7「股票」欄的上漲、下跌家數（不含漲停、跌停的括號數字）。
- 來源失敗時，對應的欄位是 `null`（`index.taiex`、`index.turnover`、`index.breadth`、`sectors`、`institutional`、`margin`、`ex_dividend`）。MI_INDEX 某一個表解析失敗時，只有那個表對應的欄位是 `null`。`etfs` 一定列出觀察清單每一檔，抓不到的數字和 `display` 是 `null`。`news` 只放抓到的。
- `warnings`：資料拿到了但有意外（清單外的類指數、缺類股、ETF 的漲跌不是一般格式、每日收盤行情裡沒有某一檔、ETF 收盤價或成交股數看不懂（例如沒成交的 `--`）、T86 裡沒有某一檔、除權息預告的現金股利看不懂、開休市清單有判斷不了的列或沒有當年日期；v2：鉅亨網列表有幾則沒有 `content`、內文存不進 `.cache/cnyes/`）。不影響結束碼。
- ETF 的自營商 =「自營商買賣超股數」（自行買賣 + 避險）。
- `ex_dividend[].type` 照證交所的「息」「權」「權息」；`cash_dividend` 有公告時 `display` 是去掉多餘 0 的數字加「元」（`0.12000000` → `0.12 元`）；還沒公告（空字串或「待公告實際收益分配金額」）時 `cash_dividend` 是 `null`、`display` 是「尚未公告」。範圍是報告日到報告日 + 14 天（含頭尾）。
- ETF 的「漲跌(+/-)」不是 `+`、`-`，也不是平盤（空白、漲跌價差 0）時（例如除權息當天的 `X`），`change`、`change_pct` 和 `display.change_pct` 是 `null`，並記一筆 `warnings`；收盤價、成交量照常。
- 四捨五入後是 0 的值不加正負號（`0.00%`、`0.0 億`、`0 張`）。
- 報告日休市（結束碼 3）時，JSON 只有 `report_date`、`data_date`、`market_open_today: false`、`holiday_source`、`generated_at`。
- 欄位可以調整，改了要同步更新本節。

## 7. 測試

- `pytest`，**測試不打網路**。第一次在雲端抓到的真實回應存成 `tests/fixtures/`，解析器用 fixture 測。
- 一定要有的測試：
  - 民國日期轉換（`1151009`、`115/10/06`、`115年10月06日`）
  - HTML 清理、千分位數字、負數
  - 交易日判斷：一般週間、週一（資料日是上週五）、2026-10-09 補假、2026-10-12（一）的資料日是 10/8、抓不到清單
  - 每一種 `display` 格式（含 10/6 的實際值）
  - 新聞去重、時間範圍過濾
  - Markdown 轉 Telegram HTML、跳脫、超過 4,096 字的拆分
  - **token 不會出現在任何輸出或錯誤訊息裡**（用假 token 讓請求失敗，檢查例外訊息和 log）
- `check` 不寫自動測試，它本身就是連線測試。

## 8. v2：讀新聞內文、整理（2026-10-08 上線）

v1 的 AI 只能照抄數字、只看標題。v2 讓 AI 讀挑中新聞的內文，自己寫摘要，並把數字和新聞連起來。兩條底線不變：每一句都要對得上 JSON 欄位或某篇內文；只寫「發生了什麼、今天有什麼」，新聞裡的分析師看法、預測、目標價、推薦個股一律不寫進報告。

### 8.1 `python -m brief articles <網址>...`

- 抓指定新聞的內文，輸出 JSON 到**標準輸出**：`[{"url", "source", "title", "ok", "error", "paragraphs": [...], "chars", "truncated"}]`。每篇最多 2,000 字（超過就截斷，記 `truncated: true`；沒截斷是 `false`）。`chars` 是 `paragraphs` 的字數合計。`<br>` 當成分段。同一個網址重複給只抓一次。
- **內文不寫進 repo**（版權；repo 之後可能公開）。測試 fixture 只放內文容器和前兩段，不放整頁。
- 請求規矩同第 5 節（逾時 15 秒、重試 1 次、同網域間隔至少 3 秒）。
- 支援的網站（2026-10-07 在台灣網路測過）：

| 來源 | 網址 | 內文在哪 | 注意 |
|---|---|---|---|
| 經濟日報 | `money.udn.com/money/story/...` | `section.article-body__editor` 裡的 `<p>` | 容器裡的 `<h1>`～`<h6>` 也算一段：行事曆的「台灣」「國際」小標是 `<p><h2>台灣</h2></p>`（雲端 2026-10-07 實測）。`title` 取 og:title，去掉後面的「 \| 分類 \| 經濟日報」 |
| Yahoo股市 | `tw.stock.yahoo.com/news/...`、`tw.news.yahoo.com/...` | `<article>` 裡的 `<p>` | 第一段是「將 Yahoo 加入 Google 優先推薦來源…」這類標語，要濾掉；結尾可能有「延伸閱讀」「更多…報導」，也濾掉。雲端 2026-10-07 實測：標語是 `<article>` 裡 `<header>` 的「加入為 Google 偏好來源」「將 Yahoo 設為首選來源…」，`<header>` 整塊跳過，另外用文字比對；結尾也有「【看原文連結】」；圖說（「▲…（記者…攝）」）也是 `<p>`，留著 |
| 鉅亨網 | `news.cnyes.com/news/id/<newsId>` | 不抓網頁（網頁的 `<p>` 抓到的是側欄標題，單篇 API `/media/api/v1/news/<id>` 回 422）。`collect` 抓列表時，列表 API 每則都附 `content`（HTML 全文），把它存成 `.cache/cnyes/<newsId>.txt`（去 HTML），`articles` 遇到鉅亨網址就讀這個檔 | `.cache/` 加進 `.gitignore`。`content` 是跳脫過的 HTML（`&lt;p&gt;…`），先還原再取 `<p>`，表格不取。快取檔：第一行標題、第二行空白、之後一段一行。沒有 `content` 的記一筆 `warnings`，存不進快取也只記 `warnings`，都不影響結束碼 |

- 不支援的網站、抓不到、解析不到內文：`ok: false` 加上 `error`，不中止其他篇。結束碼：全部成功 0，有失敗 2，參數錯誤 1。
- `check` 加上 `tw.news.yahoo.com`（名稱 `article_yahoo_news`，請求 `https://tw.news.yahoo.com/`）。

### 8.2 報告格式（v2）

```
**📊 台股盤前整理｜<報告日>**
資料日：<資料日>

**今日重點**
1. <對照指數漲跌、漲跌家數、三大法人買賣超的方向；不一致要點出來>
2. <把數字和新聞內文連起來，例如法人賣超和某篇新聞提到的賣超對象；連不起來就改寫新聞裡最多篇提到的事>
3. <今天要注意的事件；沒有就寫「今天沒有查到特別事件」>

**大盤** …（同 v1）
**法人** …（同 v1）
**融資融券** …（同 v1）
**類股** …（同 v1）
**ETF** …（同 v1）
**近期除息** …（同 v1）

**新聞**
- [標題](網址)（來源）
  <1～2 句：這則在說什麼。只寫事實，不寫文中的看法、預測、目標價>
（5～8 則；內文抓不到的只放標題）

**今天要注意**
- <從「重要財經行事曆」內文和除息預告整理出今天的事件>

今日缺少：<有才寫>
以上為公開資訊整理，不構成投資建議。
```

- 新聞從 JSON 的 `news` 挑 5～8 則；標題有「重要財經行事曆」的那篇（經濟日報每天早上會發）**另外**用 `articles` 抓，只用在「今天要注意」，不列進新聞。
- 數字區照舊照抄 `display`。新聞摘要裡的數字只能用內文裡原樣出現的。
- 全文 3,500 字以內。
