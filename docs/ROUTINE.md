# 每日 Routine 設定

在 [claude.ai/code/routines](https://claude.ai/code/routines) 建立。

| 項目 | 設定 |
|---|---|
| 名稱 | 台股盤前資訊整理 |
| Repo | 你自己的 repo（fork 或複製這個專案後推上 GitHub） |
| 環境 | `tw-brief`（網路與環境變數見下方） |
| 排程 | 週一到週五 08:07（避開整點，官方說整點可能晚幾分鐘才開始） |
| 模型 | Sonnet 5.5（PoC 期間固定不換） |
| Connectors | 全部移除，用不到 |

## 環境 `tw-brief`

- **網路**：Custom，勾選「Also include default list of common package managers」，Allowed domains：

  ```
  www.twse.com.tw
  openapi.twse.com.tw
  tw.stock.yahoo.com
  money.udn.com
  api.cnyes.com
  api.telegram.org
  pypi.org
  files.pythonhosted.org
  ```

  v1.1 起不再請求 `openapi.twse.com.tw`，可以從清單拿掉（留著也沒影響）。第一階段的 session 連 pypi 被擋（原因沒確認：可能是「包含預設清單」沒勾到，或桌面版沒有這個選項），所以 2026-10-07 手動加了 pypi 那兩個。Routine 本身不需要安裝套件，留著備用。

- **環境變數**：

  ```
  TELEGRAM_BOT_TOKEN=（BotFather 給的 token）
  TELEGRAM_CHAT_ID=（自己的 chat id）
  TZ=Asia/Taipei
  ```

  Telegram 的 token 放在網址裡（`/bot<token>/sendMessage`），官方的 API credentials 是把金鑰加在 header，預期用不了，所以先放環境變數。用一個專用的新 bot，外洩時到 BotFather 撤銷就好。

## Routine 的指示（貼在 claude.ai）

指示只留兩句，叫它讀下一節。之後要改步驟、規則、格式，改這個檔案就好，不用再去 claude.ai 改 Routine。

```
你是我的台股盤前資訊整理助理，只整理公開資訊，不做任何投資建議。
請完整照著 repo 裡 docs/ROUTINE.md 的「每次執行的步驟」執行，規則和報告格式都在那一節。
```

## 每次執行的步驟

1. 讀 CLAUDE.md 和 docs/SPEC.md（第 8 節是 v2 的報告格式）。
2. 一律用 `/usr/bin/python3.13 -m brief` 執行，在 repo 根目錄，不用安裝套件。**不要用 `python3`**：排程主機上的 `python3` 是 3.11，沒有 requests（2026-10-07 第一次 Routine 踩到）。`/usr/bin/python3.13` 不存在或找不到 requests 時，找一個 import 得到 requests 的 Python 來用，並記進 PITFALLS。
3. 執行 `collect`，看結束碼：
   - 3（今天休市）：寫 `reports/<報告日>.md`，內容只有一行「今天休市，不發盤前整理。」，用 `send` 送出，跳到第 8 步。
   - 1（失敗）：寫 `reports/<報告日>.md`，內容是「今天的盤前整理失敗：<一句話原因>」，用 `send` 送出，跳到第 8 步。
   - 0 或 2：繼續。
4. 讀 `data/<報告日>.json`，從 `news` 挑 5～8 則跟大盤、觀察清單 ETF、主要產業最相關的新聞。另外找標題有「<報告日的月日>重要財經行事曆」的那篇（例如「10月8日重要財經行事曆」），有就一起抓，只用在「今天要注意」。
5. 執行 `articles <挑中的網址>...`，讀它輸出的內文。**內文不要存成檔案、不要 commit。**
6. 照 SPEC 8.2 的格式和下面的規則寫 `reports/<報告日>.md`。
7. 執行 `send reports/<報告日>.md`。
8. 把 `data/` 和 `reports/` 的新檔案 commit（`.cache/` 不進 git），push 到 main。commit 訊息：「data: <報告日> 盤前整理」。系統另外要求推到指定的 `claude/` 分支時可以照做，但 main 一定要有。
9. 這次執行遇到任何意外（來源失敗、被擋、內文抓不到、格式變了、規格沒寫到），在 `docs/PITFALLS.md` 加一列，一起 commit。

### 規則

- **數字區**（大盤、法人、融資融券、類股、ETF、除息）的數字一律照抄 JSON 的 `display`。不能自己換算，不能用你自己知道的數字，也不能上網另外查。
- **新聞摘要**寫 1～2 句「這則在說什麼」，只寫事實（發生了什麼、誰宣布了什麼）。文中分析師或專家的看法、預測、目標價、推薦個股一律不寫。摘要裡的數字必須在內文原樣出現。內文抓不到的只放標題，不要用標題猜內容。
- **新聞和 JSON 的數字對不上時**（例如成交金額、法人買賣超金額，算法可能不同），數字區照 JSON，新聞摘要不要提那個數字。
- **今日重點**三點：
  1. 對照指數漲跌、漲跌家數（`breadth.up`、`breadth.down` 哪個多）、三大法人各自買超或賣超。方向不一致要點出來。
  2. 把數字和新聞內文連起來（例如法人賣超和某篇內文列出的賣超對象、觀察清單 ETF 有沒有在裡面）。連不起來就寫新聞內文裡最多篇提到的事。
  3. 今天要注意的事件（行事曆、今天除息的觀察清單 ETF）；沒有就寫「今天沒有查到特別事件」。
  每一點都要對得上 JSON 欄位或某篇內文；只描述，不推測原因、不預測走勢。
- 不寫買賣建議、目標價、「看好」「看壞」這類判斷。
- JSON 裡是 `null` 的數字寫「無資料」。
- `sources` 失敗、行事曆找不到、內文抓不到的，在最後的「今日缺少」寫出來。
- 全文 3,500 字以內。

### 格式

照 SPEC 8.2（標題不要加「v2 測試」）。
