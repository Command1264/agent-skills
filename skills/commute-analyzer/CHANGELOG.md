# Changelog

所有值得注意的變更都記錄在此。版本遵循 Semantic Versioning。

## [Unreleased]

### Added

- 新增 config／plan request v2 的 Named Locations、任意起訖點、2–12 個固定順序 Points，及可與
  outbound 不同或由 `reverse_outbound` 展開的 return。
- 新增單一 v2 Plan Builder；preview 分開計算 Journey、Compute Routes request、route legs、最大
  HTTP requests 與推定 SKU，且不顯示 address 或 Place ID。
- 新增 v1 Compatibility Adapter；有效的成對 v1 inputs 會產生 plan v2，不會改寫私人 config。

### Changed

- `capabilities` 與 `config check` 升級為 v2 planning contract，並要求 `google-routes` 提供 schema v2、
  `itinerary_summary` 與固定順序 waypoint 能力。
- v2 runtime 將既有 plan v1 視為必須重新離線產生。
- `run` 改為逐 sample 查詢 itinerary v2，驗證 Points／legs／totals 後，以 Journey 產生方向、每日來回、
  每週與四週統計及排名。
- 私人 JSON／Markdown 報告與 usage ledger 升級為 v2；報告保留 labels 與 legs，不保存位置或 provider
  point Place ID；Markdown 會轉義自訂 label，避免被解讀為連結、圖片或額外段落。

### Fixed

- 修正 Windows PowerShell 以 UTF-8 native pipe 傳入含中文的 plan request 時，Python 可能依系統
  code page 解碼並在計算 `plan_id` 時觸發 `UnicodeEncodeError`；CLI 現在明確固定 UTF-8 stdio。

### Development status

- Issue #20 階段 2A–2C 已完成本機 schema、planning、run、分析、私人產物與 mock E2E；正式
  v2.0.0 仍須完成獨立的真實 API smoke 與發布驗收。

## [1.1.0] - 2026-09-13

### Added

- 新增完全離線的 `config path` 與 `config check`，安全顯示路徑解析與設定有效性。

### Changed

- Windows config 改用 `%USERPROFILE%\.config`，reports 與 ledger 改用
  `%USERPROFILE%\.local\share`，讓 packaged 與 unpackaged runtime 共用同一實體檔案。
- 新預設 config 不存在時，保留目前 runtime 可見的舊 `%APPDATA%` config fallback，並提示
  人工遷移；不自動複製或搬移私人資料。

### Fixed

- 修正 Microsoft Store／MSIX Python 因 AppData virtualization 找不到 PowerShell 已建立設定的問題。

## [1.0.0] - 2026-09-13

### Added

- 新增離線 `capabilities` 與 `plan`、需 API key 的 `run`。
- 新增 `google-routes` v2 fail-closed 相依性檢查；credential 完全由 provider Skill 管理。
- 新增一至四週、星期、公司、早晚時間與 QPM 的 plan 參數。
- 新增機車完整性排名、汽車補充統計、私人 JSON／繁體中文 Markdown 報告及 usage ledger。
- 新增發布用真實 API smoke runner，以明確 opt-in、兩種模式各一筆及零重試限制實際請求上限。
