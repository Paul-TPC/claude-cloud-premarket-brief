# 給 Claude 的規則

- 文件、commit 訊息、報告都用繁體中文。
- 這是資訊整理工具。任何輸出都不能有買賣建議、目標價、看多看空的判斷。
- **祕密**：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 只從環境變數讀。不印出、不寫進任何檔案或 log、不 commit。不要執行會把環境變數印出來的指令（`env`、`printenv`、`echo $TELEGRAM_BOT_TOKEN` 這類）。Telegram 的 token 在網址裡，例外訊息會帶出完整網址，錯誤訊息一律先遮蔽再輸出。
- **程式負責數字，AI 負責文字**：報告裡的數字一律照抄 JSON 的 `display` 欄位，不自己換算或四捨五入。
- 對外請求遵守 SPEC 的間隔、逾時、重試規定。
- 遇到任何意外（被擋、格式改變、資料缺漏、規格沒寫到的情況），在 `docs/PITFALLS.md` 加一列，再繼續。
- commit 不要加 `Co-Authored-By` 或其他署名行（repo 擁有者的要求）。
- 依賴保持最少：`requests` 加上標準函式庫。要加其他套件，先在 PR 說明理由。
