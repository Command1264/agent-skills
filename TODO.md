# 後續待辦

本文件記錄已確認、但尚未進入實作的跨版本工作。每個項目在開始前應建立或連結 GitHub Issue，
補齊範圍、相容性與驗收計畫；列在此處不代表已核准實作、API request 或任何 remote write。

## commute-analyzer：拆分大型執行期模組

**狀態**：待規劃  
**動機**：`skills/commute-analyzer/scripts/commute_analyzer.py` 已超過 2,000 行，planner、runner、
分析、報告、設定與 CLI orchestration 集中於單一檔案，增加閱讀、定位變更與獨立測試的成本。

### 方向

- 保留目前公開 CLI、JSON schemas、exit codes、privacy constraints 與 `google-routes` subprocess seam。
- 先盤點現有責任與依賴方向，再以深層 module 拆分；每個 module 應提供小而穩定的 interface，
  不建立只轉傳參數的薄層。
- 優先採用 functional core／imperative shell：驗證、正規化、plan 建立、統計與結果轉換盡量維持
  純函式及不可變資料；檔案、時間、subprocess、credential、ledger 與 report 寫入集中在外圍 adapters。
- 只有在物件需要維持明確生命週期、狀態或可替換 adapter 時才採用 class；不以 OOP 或 Functional
  Programming 的形式本身作為目標。
- 預計評估的 module seam 包含 input normalization、execution plan、dependency capabilities、
  plan execution、journey analysis、report rendering、private storage 與 CLI composition。
- 使用漸進式搬移，讓每個 checkpoint 都可由既有測試驗證並可單獨回復；不與功能擴充或 schema
  升級混在同一個變更中。

### 驗收條件

- `commute_analyzer.py` 成為薄的 CLI composition 入口，主要 domain 行為由命名清楚的 modules 擁有。
- v1 compatibility inputs、v2 plan/run、成本確認、privacy 與跨 runtime 路徑行為沒有回歸。
- 測試主要透過公開 interface 驗證；需要替換外部行為時使用既有或明確的新 adapter seam。
- repository validation、完整 unit／mock E2E、compile 與 privacy canary checks 全部通過。
- 架構與 module interface 同步到必要的 domain／ADR／開發文件；若拆分需要改公開契約，另行提案。

## 使用者訊息與報告國際化

**狀態**：待規劃  
**目標**：面向全球使用者時預設輸出英文，同時讓繁體中文等語言可以用可驗證、可維護的翻譯資源載入。

### 方向

- 將 CLI 診斷、錯誤說明、preview 摘要與 Markdown report 的人類可讀文字移出 domain logic；
  JSON 欄位、error codes、schema versions 與機器可讀值保持穩定，不隨語言改變。
- 預設 locale 設為英文，首批 bundled locales 至少包含英文與繁體中文。
- 規劃明確的 locale 選擇順序，例如 CLI option、私人 config、環境語言與英文 fallback；正式實作前
  需確認缺少翻譯、未知 locale 與 fallback 的 fail-safe 行為。
- 以 UTF-8 JSON 或 TOML 作為 language catalog 候選格式。Issue 規劃階段比較標準函式庫支援、
  schema 驗證、translator 易讀性、巢狀 key、placeholder 與跨平台行為後再定案，不同時維護兩種格式。
- language catalog 只能保存訊息模板，不保存私人地址、API key、provider response 或 runtime config。
- 先建立 message key inventory 與 placeholder contract，再替換硬編碼訊息，避免以自由文字作為程式控制流。
- 更新目前「繁體中文為權威使用者文件」的文件政策時，分開定義 repository 文件語言與 runtime
  預設輸出語言；runtime 改為英文不會自動要求所有維護文件立即翻譯。

### 驗收條件

- 未指定 locale 時，所有新增的 CLI 人類可讀訊息與 Markdown report 預設為英文。
- 指定繁體中文時，關鍵 CLI 流程、錯誤、preview 與 report 均有完整翻譯，且沒有混入非預期語言。
- JSON stdout 仍是 strict JSON envelope；進度與診斷維持在 stderr，語言切換不改 schema 或 error code。
- 缺少 key、placeholder 不一致、無效 catalog 與未知 locale 有自動化測試及可操作的 fallback／錯誤。
- Windows、macOS、Linux 的 UTF-8 輸出與 catalog 載入測試通過，且不需要新增不必要的 production dependency。
- README、Skill 說明、CLI contract、examples 與 changelog 清楚說明 locale 設定、預設值及支援範圍。

## 建議順序

1. 先完成目前 `commute-analyzer v2.0.0` 的正式 smoke 與發布驗收，固定既有行為基線。
2. 建立 module 拆分 Issue，先以 characterization tests 固定現況，再做不改行為的漸進式重構。
3. 在新的 module seam 穩定後建立 internationalization Issue，決定 catalog 格式與 locale contract，
   再逐步搬移人類可讀訊息。

這個順序讓國際化不必綁在目前 2,000 行以上的單一實作中，也能以既有公開契約判定重構是否回歸。
