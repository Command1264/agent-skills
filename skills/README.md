# Skills

每個可獨立安裝的 Skill 使用 `skills/<skill-name>/SKILL.md` 作為入口。正式 Skill
必須完成對應 GitHub Issue 的驗收後才可從 `main` 發布。`develop` 與 task branch
可以包含尚待驗收的 Skill。目前 `google-routes` 穩定版為 v2.1.0，
`commute-analyzer` 為 v2.0.0，[`new-project-worktree`](new-project-worktree/SKILL.md) 為 v1.1.0。

撰寫規則請見 [`docs/agents/skill-authoring.md`](../docs/agents/skill-authoring.md)。

[`orient-next-step`](orient-next-step/SKILL.md) 已匯入開發分支，提供唯讀專案定位與下一步建議，
尚未發布。公開名稱不含作者前綴；既有本機 `command1264-orient-next-step` 安裝保留，
待新名稱正式發布後再由使用者決定是否替換，避免同時安裝兩份功能相同的 Skill。
