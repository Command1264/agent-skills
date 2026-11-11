# 獨立版本化並驗證 Skill 相容性

> Git tag 與 GitHub Release 的命名自整庫 `v1.0.0` 起改由 [ADR 0011](0011-version-skill-library-releases.md) 定義。本紀錄的 Skill 獨立版本與相依驗證決策仍有效。

每個 Skill 使用自己的 SemVer、`CHANGELOG.md` 與 `<skill-name>-v<version>` Git tag，tag 只指向 `main` 上通過 release gate 的 commit；`develop` 不作為穩定安裝來源。因為 `npx skills` 目前不解析 Skill 間的版本相依，`google-routes` 提供不呼叫 API 的 `capabilities` 命令，`commute-analyzer` 在執行前驗證 Skill version、CLI contract version、schema、交通模式與 output profile，缺少或不相容時採 fail-closed。真實 API smoke test 只在首次發布、HTTP adapter、認證、field mask、response parser 或外部契約疑似改變時執行，且最多一筆 `TWO_WHEELER` 與一筆 `DRIVE`。這讓不同 Skill 能獨立演進並保留可重現版本，代價是 shared change 必須辨識並提升每個受影響 Skill 的版本，且安裝工具仍不會自動解決相依性。
