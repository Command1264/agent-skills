# Issue 追蹤系統：GitHub

本 repository 的 Issue 與規格統一存放於 GitHub Issues。所有 Issue 操作
使用 `gh` CLI。

本 repository 目前尚未設定 GitHub remote。在 remote 設定完成前，應將
GitHub 操作回報為受阻，不得自行改用其他 Issue 追蹤方式。

## 操作慣例

- 建立：`gh issue create --title "..." --body "..."`
- 讀取：`gh issue view <number> --comments`
- 列出：`gh issue list --state open`
- 留言：`gh issue comment <number> --body "..."`
- 加上 label：`gh issue edit <number> --add-label "..."`
- 移除 label：`gh issue edit <number> --remove-label "..."`
- 關閉：`gh issue close <number> --comment "..."`

GitHub remote 設定完成後，應在 repository 內執行以上命令，讓 `gh`
自動判斷目標 repository。

## Pull Request 是否納入 triage

PRs as a request surface: no.

除非日後明確修改此設定，否則 Pull Request 不屬於 Issue triage queue。

## Skill 用語

當 Skill 要求「發布至 Issue 追蹤系統」時，建立 GitHub Issue。

當 Skill 要求「取得相關 ticket」時，讀取對應的 GitHub Issue、留言與
labels。

## Wayfinding 操作

若未來的 Skill 使用 wayfinding map：

- 使用一個帶有 `wayfinder:map` label 的 Issue 作為 map。
- GitHub 支援時，使用 sub-issues 表示子 ticket。
- 依 ticket 類型使用 `wayfinder:research`、`wayfinder:prototype`、
  `wayfinder:grilling` 或 `wayfinder:task` label。
- GitHub 支援時，使用原生 Issue dependencies 表示阻擋關係。
- 開始工作前，先將 ticket 指派給執行者。
- 完成後記錄答案、關閉 Issue，並更新 map。
