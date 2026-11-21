# 版本與發布規則

處理 Skill version、changelog、tag、GitHub Release、安裝文件、穩定分支或 release gate
時適用。

## 分支角色

- `main` 是 GitHub default branch 與穩定安裝基線。
- `develop` 是日常整合中心；一般 task branch 從最新且已確認的 `develop` 建立，PR 目標
  明確指定為 `develop`。
- task branch 通過 Agent 驗證後仍需使用者驗收；只有使用者針對明確 head commit 與目標
  授權，才可 merge。
- `develop` 到 `main` 是發布整合，不由一般 task merge 授權隱含取得。

## Skill 庫版本與各 Skill 版本

- 從 `v1.0.0` 起，Git tag 與 GitHub Release 標題一律使用相同的整庫 SemVer：`vX.Y.Z`，
  不加 Skill 名稱。每個 tag 固定指向 `main` 上已通過 release gate 的一個 commit。
- 整庫版本按公開行為的變更程度遞增：不相容變更升 major；相容的新功能或新 Skill 升 minor；
  相容修正升 patch。同一次發布有多種變更時，取最高等級。
- 每個 Skill 的獨立 SemVer 仍記在 `skills/<skill-name>/CHANGELOG.md`。發布說明列出有變更的
  Skill 與其版本；共用變更須逐一判斷影響，不因整庫升版而同步調升未變更的 Skill。
- Skill 的不相容介面變更仍須升 major 或使用新的 contract/schema version，並提供明確的
  遷移與 fail-closed 行為。
- 已發布的帶前綴 tag 和對應 Release 保留原樣。已固定至舊 tag 的安裝仍可重現；要改用整庫版本，
  須明確選擇新的 tag 安裝。決策背景見 [ADR 0011](../adr/0011-version-skill-library-releases.md)。

## Release gate

- 通過 Windows、Ubuntu、macOS 的相關 CI、Skill discovery、schema examples、unit tests、
  mock integration tests、文件連結與 artifact inspection。
- 對使用外部 API 的 Skill，首次發布或 HTTP adapter、認證、field mask、response parser、
  provider contract 改變時，執行受硬上限保護的本機真實 API smoke test。
- 發布說明分開記錄 Agent 驗證、使用者驗收、真實外部服務證據與未驗證限制。
- 在 README 加入安裝或 pinning 命令前，必須以當時版本的 `npx skills` 實際驗證；不只依
  舊文件或推測的 Git ref 語法。

## Remote 操作

Push、PR、merge、tag、GitHub Release 與 branch protection 都需要當前任務的明確授權。
Merge 後依全域 Git 交付規則確認 remote ref、同步基線並清理已合併 task branch／Worktree。
