# Changelog

本 Skill 依 [Semantic Versioning](https://semver.org/) 獨立版本化。

## [1.0.0] - Unreleased

### Added

- 新增嚴格、帶版本的批次 JSON CLI 與不呼叫 API 的 `capabilities`。
- 支援 `DRIVE` 與 `TWO_WHEELER` 的 `summary` route result。
- 新增 60 QPM 主動節流、`Retry-After` 與最多兩次有限重試。
- 新增 mock integration tests 與受兩筆上限保護的 opt-in smoke test。
