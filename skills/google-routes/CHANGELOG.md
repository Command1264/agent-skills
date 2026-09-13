# Changelog

本 Skill 依 [Semantic Versioning](https://semver.org/) 獨立版本化。

## [2.1.0] - 2026-09-13

### Added

- 新增 query／result schema v2 與 `itinerary_summary`，支援 2–12 個固定順序命名 Points。
- 新增 0–10 個 Google intermediate stopovers 與逐段 route leg 正規化。

### Changed

- capabilities 宣告 waypoint 限制、固定順序策略與交通模式推定 SKU。
- Skill 候選版本提升至 2.1.0；query v1 與 `summary` 保持相容。

## [2.0.0] - 2026-09-13

### Added

- 新增 `credentials path`、`credentials check` 與互動式 `credentials set`。
- 新增 provider-owned、帶 schema 的 TOML secret file 與原子更新流程。

### Changed

- CLI contract 提升至 2.0.0；route result schema 維持 v1，但其 `cli_contract_version` 改為 2.0.0。
- Windows credential 改用使用者主目錄下的 `.config`，避免 Microsoft Store Python 的 AppData 重導。

### Removed

- 移除 `GOOGLE_MAPS_API_KEY` credential 來源與 fallback；非空舊變數會使 query／smoke fail-closed。

## [1.0.0] - 2026-09-12

### Added

- 新增嚴格、帶版本的批次 JSON CLI 與不呼叫 API 的 `capabilities`。
- 支援 `DRIVE` 與 `TWO_WHEELER` 的 `summary` route result。
- 新增 60 QPM 主動節流、`Retry-After` 與最多兩次有限重試。
- 新增 mock integration tests 與受兩筆上限保護的 opt-in smoke test。
