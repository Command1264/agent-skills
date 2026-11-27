# Changelog

本 Skill 依 [Semantic Versioning](https://semver.org/) 獨立版本化。

## [Unreleased]

### Added

- 新增 `idea-assessment`：釐清想法、調查開源與閉源競品、需求、趨勢與 AI 替代風險，依九個面向
  0–5 分評分，給出「值得做／先驗證／不建議」判決、最便宜的驗證實驗與放棄條件。
- `scripts/idea_assessment.py`：`path` 顯示報告根目錄與來源；`init` 建立 `<日期>-<slug>` 報告資料夾；
  `render` 依 `assessment-v1` 驗證評估檔（含來源網址與 `[n]` 引用），產生單一檔案、離線可開、支援深色模式與
  手機寬度的 `report.html`，以及 `report.md` 文字備份與由「不推薦」到「推薦」的 `chart.svg` 長條圖。
- 報告預設存放在各平台的使用者私人資料夾（Windows、macOS、Linux），可用 `--output-dir` 或設定檔
  `output_root` 改為相對或絕對路徑。
- 三個行為驗收案例（`evals/`）。
