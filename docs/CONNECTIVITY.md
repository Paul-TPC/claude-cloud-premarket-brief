# 雲端機器連線測試

在 Claude Code 雲端 session 的機器上執行 `python -m brief check` 的結果。機器在國外，對外 HTTPS 經過環境的 proxy。網址的日期參數用 2026-10-06（資料日），STOCK_DAY 用 0050，T86 照 SPEC 用 `selectType=ALL`。

連不到的照實記錄，沒有做任何繞過（沒有改 User-Agent 以外的標頭、沒有換 IP、沒有加長間隔以外的手段）。請求規矩照 SPEC：逾時 15 秒、失敗重試 1 次、同網域（`twse.com.tw` 算一個）間隔至少 3 秒。

## 重點

- **新聞三個來源、api.telegram.org：每次都連得到。**
- **證交所：TCP/TLS 連得上，但常常回「因為安全性考量，您所執行的頁面無法呈現 / FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED」擋頁**（伺服器標頭 `HiNetCDN`，附一串錯誤代碼）。
  - openapi.twse.com.tw 的擋頁是 **HTTP 200**，只看狀態碼會誤判成功。
  - www.twse.com.tw 的擋頁是 **HTTP 307**，但沒有 `Location` 標頭，所以 requests 不會跟過去，最後拿到的就是 307。
  - 同一批請求裡有的成功、有的被擋；後來的請求被擋的比例變高（03:03 時 0050 的 STOCK_DAY 正常，03:14 被擋）。原因不知道，推測和國外 IP 或累積的請求量有關。
- 03:02 第一次 `check` 只看狀態碼，所以回報「全部連得到」，**這個結果不可靠**。之後 `check` 改成也判斷擋頁，03:14 重跑的結果才是準的。

## v2（2026-10-07 23:45～23:54，台灣時間）

v2 的 `articles` 要抓經濟日報、Yahoo（`tw.stock.yahoo.com`、`tw.news.yahoo.com`）的新聞網頁；鉅亨網不抓網頁，讀 `collect` 存的快取。這一輪為了省請求沒有跑 `check`；`tw.news.yahoo.com` 在抓 fixture 和驗收時都連得到。沒有遇到擋頁或重試。

### 23:45：抓 v2 的 fixture（每個網址一次）

原始網頁只存在 repo 外面，repo 裡的 fixture 只有內文容器和前兩段。

| 網址 | 結果 | 大小 | 耗時（ms） |
|---|---|---|---|
| 經濟日報 `money/story/5607/9799374`（10月7日重要財經行事曆） | 200 正常 | 261,528 bytes | 931 |
| 經濟日報 `money/story/5710/9798786` | 200 正常 | 273,183 bytes | 448 |
| `tw.stock.yahoo.com/news/…-115810399.html` | 200 正常 | 465,419 bytes | 941 |
| `tw.news.yahoo.com/…-133154244.html` | 200 正常 | 516,621 bytes | 1103 |
| 鉅亨網列表 API（`limit=100`） | 200 正常 | 150,522 bytes | 799 |

### 23:51：`collect --date 2026-10-08`（資料日 2026-10-07）

結束碼 0，鉅亨網 30 則的內文存進 `.cache/cnyes/`。

| 來源 | 結果 | 耗時（ms） |
|---|---|---|
| twse_holiday | 正常 | 624 |
| twse_index（MI_INDEX ALLBUT0999） | 正常 | 267 |
| twse_institutional、twse_margin | 正常 | 116、113 |
| twse_etf_institutional（T86 ALL） | 正常 | 315 |
| twse_ex_dividend | 正常 | 113 |
| news_yahoo、news_udn、news_cnyes | 正常 | 805、952、914 |

### 23:52：`articles`（8 篇）

網頁請求 5 個（Yahoo 4 個：`tw.stock.yahoo.com` 1、`tw.news.yahoo.com` 3；經濟日報 1 個），都 HTTP 成功；鉅亨網 3 篇讀快取，沒有請求。結束碼 2：經濟日報那篇找得到內文容器但沒有段落（見 PITFALLS）。

### 23:54：`send`

`api.telegram.org` 送出 1 則，成功。

## v1.1（2026-10-07 03:41～03:49，台灣時間）

v1.1 不再用 openapi.twse.com.tw，證交所的請求從 12 個減到 6 個，全部在 www.twse.com.tw。這一輪沒有跑 `check`，只抓新的 fixture 和實際跑一次 `collect`，都沒有遇到擋頁。

### 03:41：抓新的 fixture（每個網址一次）

| 網址 | 結果 | 大小 | 耗時（ms） |
|---|---|---|---|
| rwd holidaySchedule | 200 正常 | 2,783 bytes | 1497 |
| MI_INDEX `date=20261006&type=ALLBUT0999` | 200 正常 | 247,344 bytes | 267 |
| rwd exRight/TWT48U | 200 正常 | 17,461 bytes | 108 |

### 03:49：實際跑 `collect`（報告日 2026-10-07）

距離上一次請求證交所約 7 分鐘。結束碼 0。

| 來源 | 結果 | 耗時（ms） |
|---|---|---|
| twse_holiday | 第一次連線被重設（Connection reset by peer），重試成功 | 9789（兩次合計） |
| twse_index（MI_INDEX ALLBUT0999） | 正常 | 255 |
| twse_institutional、twse_margin | 正常 | 105、108 |
| twse_etf_institutional（T86 ALL） | 正常 | 300 |
| twse_ex_dividend（rwd TWT48U） | 正常 | 104 |
| news_yahoo、news_udn、news_cnyes | 正常 | 914、929、758 |

## 2026-10-07 03:14（台灣時間）：`check`，有判斷擋頁

結束碼 2。

| 來源 | 狀態碼 | 耗時（ms） | 錯誤訊息 |
|---|---|---|---|
| twse_holiday | 200 | 2619 | 擋頁（重試 1 次也是擋頁），錯誤代碼 7641438221885332067 |
| twse_index | 200 | 2091 | |
| twse_turnover | 200 | 380 | |
| twse_institutional | 200 | 376 | |
| twse_margin | 200 | 379 | |
| twse_etf_institutional | 200 | 405 | |
| twse_etf_price（0050） | 307 | 553 | 擋頁（重試 1 次也是擋頁），錯誤代碼 7641438221885343217 |
| twse_ex_dividend | 200 | 2839 | 擋頁（重試 1 次也是擋頁），錯誤代碼 7641438221885346964 |
| news_yahoo | 200 | 538 | |
| news_udn | 200 | 912 | |
| news_cnyes | 200 | 713 | |
| telegram（`https://api.telegram.org`，不帶 token、不跟轉址） | 302 | 765 | |

耗時包含重試那一次的請求時間，不包含 3 秒間隔。

## 2026-10-07 03:02：`check`，只看狀態碼（不可靠）

結束碼 0。這時的 `check` 還沒有判斷擋頁，openapi 的擋頁是 200，所以全部顯示成功。

| 來源 | 狀態碼 | 耗時（ms） | 錯誤訊息 |
|---|---|---|---|
| twse_holiday | 200 | 1251 | （沒檢查內容） |
| twse_index | 200 | 1355 | |
| twse_turnover | 200 | 107 | |
| twse_institutional | 200 | 113 | |
| twse_margin | 200 | 109 | |
| twse_etf_institutional | 200 | 400 | |
| twse_etf_price（0050） | 200 | 104 | |
| twse_ex_dividend | 200 | 1564 | （沒檢查內容） |
| news_yahoo | 200 | 756 | |
| news_udn | 200 | 814 | |
| news_cnyes | 200 | 1150 | |
| telegram | 302 | 802 | |

## 抓 fixture 時每個網址的結果

用 `tools/fetch_fixtures.py`（請求規矩和 collect 一樣）抓 2026-10-06 的資料存成 `tests/fixtures/`。

| 時間 | 網址 | 結果 |
|---|---|---|
| 03:03 | holidaySchedule | 200 擋頁 |
| 03:03 | MI_INDEX、FMTQIK、BFI82U、MI_MARGN | 200 正常 |
| 03:03 | T86 `selectType=0099P`（想縮小範圍） | 307 擋頁 |
| 03:03 | STOCK_DAY 0050、00878、00919 | 200 正常 |
| 03:03 | STOCK_DAY 006208、0056 | 307 擋頁 |
| 03:03 | TWT48U_ALL | 200 擋頁 |
| 03:03 | 三個新聞來源 | 200 正常 |
| 03:06 | holidaySchedule | 第一次 200 擋頁，重試成功 |
| 03:07 | T86 `selectType=0099P` | 第一次連線被重設（Connection reset by peer），重試 307 擋頁；回應標頭有 `rule: T86` |
| 03:07 | STOCK_DAY 006208、0056 | 兩次都 307 擋頁 |
| 03:07 | TWT48U_ALL | 200 正常 |
| 03:10 | T86 `selectType=ALL` | 200 正常（2,524,030 bytes） |
| 03:10 | STOCK_DAY 006208、0056 | 兩次都 307 擋頁 |
| 03:31 | STOCK_DAY 006208、0056 | 200 正常（collect 跑完之後補抓） |

## 2026-10-07 03:30：實際跑 `collect`（報告日 2026-10-07）

停了約 15 分鐘沒請求證交所之後跑。結束碼 2。

| 來源 | 結果 | 耗時（ms） |
|---|---|---|
| twse_holiday | 兩次都 200 擋頁 → 改用週末判斷（`holiday_source: weekend_only`） | 2894 |
| twse_index、twse_turnover、twse_institutional、twse_margin | 正常 | 911、139、115、115 |
| twse_etf_institutional（T86 ALL） | 正常 | 413 |
| twse_etf_price（0050、006208、0056、00878、00919） | 全部正常 | 257、392、249、253、261 |
| twse_ex_dividend | 兩次都 200 擋頁 → `ex_dividend: null` | 2670 |
| news_yahoo、news_udn、news_cnyes | 正常 | 796、803、719 |
