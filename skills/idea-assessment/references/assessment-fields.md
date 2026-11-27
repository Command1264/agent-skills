# 評估檔欄位

`assessment.json` 是報告的唯一內容來源；`render` 依它排版網頁，Agent 不另外手寫 HTML 或 Markdown。
完整格式見 `schemas/assessment-v1.schema.json`，可照抄 `examples/assessment.json` 的結構再替換內容。

## 寫法

- **引用**：任何文字欄位都可以寫 `[n]` 引用 `sources` 中 `id` 為 n 的來源，網頁會變成可點的連結。
  引用不存在的 id 時 `render` 會拒絕，所以先排好 `sources` 再寫內文。
- **推論**：沒有來源支持的判斷在句尾寫「（推論）」。
- **長度**：每格一兩句。網頁預設展開判決、長條圖、假設、競品、AI 風險、驗證實驗與放棄條件；
  其餘段落收合，細節寫在收合段落裡。

## 欄位

| 欄位 | 內容 |
| --- | --- |
| `idea`、`date` | 想法短名稱、評估日期（YYYY-MM-DD） |
| `verdict`、`verdict_reason` | 判決與一句最關鍵的理由；偏離判決規則時在這裡說明 |
| `dimensions` | 評分標準的九個面向，各有 `score`、`confidence`、`summary` |
| `context` | 目標使用者、痛點、想要的成果、可投入資源、已知競品；`assumed: true` 代表使用者沒說、由 Agent 假設 |
| `competitors` | 每列一個競品或替代做法：`kind` 為 `open`、`closed`、`platform`、`workaround`；`status` 為 `active`、`stale`、`shut-down`、`unknown`；有網址才填 `url` |
| `demand`、`trends` | 需求訊號與趨勢，各一到數句；趨勢包含未來兩三年的可能發展 |
| `ai_risk` | 評分標準三層檢查的回答 |
| `considerations` | 評分標準「容易忽略的面向」逐項一筆 |
| `experiment` | 要驗證的假設、步驟（`method` 陣列）、時間、成本、成功與失敗標準 |
| `kill_criteria` | 看到就該停止的具體結果 |
| `research_gaps` | 實際搜尋後仍沒有可用證據的來源類別：寫明用過的關鍵字與結果，或工具錯誤；每類都有證據時為空陣列 |
| `sources` | `id`（從 1 起）、標題、`http(s)` 網址、查閱日期 |
