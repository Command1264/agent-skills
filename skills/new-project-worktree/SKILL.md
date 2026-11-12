---
name: new-project-worktree
description: 為 Git 專案建立或預覽新的本機工作樹。從主要 checkout、子目錄或既有連結工作樹辨識專案，將新工作樹放在與 repo/ 同層的 worktrees/。適用於任務分支、隔離開發及明確指定專案旁的工作樹。
---

# 建立專案工作樹

此 Skill 可直接調用，也可在使用者要求建立或預覽專案工作樹時由模型選用。需要 Git 與 PowerShell 7.2 以上。從目標 Git 工作目錄執行下列命令，將腳本路徑替換為此 Skill 資料夾內的實際路徑。缺少相依工具時回報所缺工具。

```text
pwsh -NoProfile -File <skill>/scripts/New-ProjectWorktree.ps1 -Type feat -Name example-task -Base develop
```

1. 依使用者與專案規則選擇基線、任務類型及 kebab-case 名稱。腳本預設使用本機 `develop`。其他專案可傳入自己的本機基線，例如 `-Base main`。
2. 先執行預覽並核對 `MainRepository`、`Worktree`、`Branch` 和 `Commit`。腳本適用於主 checkout 位於 `repo/` 的布局，工作樹目標是其同層 `worktrees/<type>-<name>`。預覽不建立目錄或分支。
3. 使用者要求實際建立時，用相同參數加上 `-Apply`。成功後回報完整工作樹路徑、分支和起始 commit。當次命令會從它核對的確切 commit 建立。使用者指定固定基線時，套用前核對該分支仍指向預期 commit。
4. 若 Git 無法辨識專案、目的地不符或已有分支／工作樹，回報衝突。若建立中途失敗，檢查實際工作樹和分支登記，再決定下一步。

手動操作可在 Codex 明確指定 `$new-project-worktree`，或在終端機直接執行同一支腳本。模型選用 Skill 不會授予額外的寫入權限。
