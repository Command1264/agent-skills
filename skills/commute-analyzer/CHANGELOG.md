# Changelog

所有值得注意的變更都記錄在此。版本遵循 Semantic Versioning。

## [1.0.0] - 2026-09-13

### Added

- 新增離線 `capabilities` 與 `plan`、需 API key 的 `run`。
- 新增 `google-routes` v2 fail-closed 相依性檢查；credential 完全由 provider Skill 管理。
- 新增一至四週、星期、公司、早晚時間與 QPM 的 plan 參數。
- 新增機車完整性排名、汽車補充統計、私人 JSON／繁體中文 Markdown 報告及 usage ledger。
- 新增發布用真實 API smoke runner，以明確 opt-in、兩種模式各一筆及零重試限制實際請求上限。
