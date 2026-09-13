# Changelog

所有值得注意的變更都記錄在此。版本遵循 Semantic Versioning。

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
