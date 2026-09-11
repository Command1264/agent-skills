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

## Skill 版本

- 每個 Skill 使用獨立 SemVer 與 `skills/<skill-name>/CHANGELOG.md`。
- Tag 格式為 `<skill-name>-v<version>`，只可指向 `main` 上已通過 release gate 的 commit。
- Shared change 必須列出所有受影響的 Skills，分別判斷版本提升與 changelog；不使用整庫
  版本掩蓋相容性影響。
- Breaking interface change 必須使用新 major 或新 contract/schema version，並提供明確
  遷移與 fail-closed 行為。

## Release gate

- 通過 Windows、Ubuntu、macOS 的相關 CI、Skill discovery、schema examples、unit tests、
  mock integration tests、文件連結與 artifact inspection。
- 首次發布，或 HTTP adapter、認證、field mask、response parser、provider contract 改變時，
  執行受硬上限保護的本機真實 API smoke test。
- 發布說明分開記錄 Agent 驗證、使用者驗收、真實外部服務證據與未驗證限制。
- 在 README 加入安裝或 pinning 命令前，必須以當時版本的 `npx skills` 實際驗證；不只依
  舊文件或推測的 Git ref 語法。

## Remote 操作

Push、PR、merge、tag、GitHub Release 與 branch protection 都需要當前任務的明確授權。
Merge 後依全域 Git 交付規則確認 remote ref、同步基線並清理已合併 task branch／Worktree。
