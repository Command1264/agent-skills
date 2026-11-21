# 變更紀錄

## v1.0.0

- 新增獨立的專案工作樹 Skill，使用同一份 PowerShell 7 腳本預覽或建立。
- 支援使用者指定 Skill 與模型依任務選用。
- 任務分支改為 `agent/<type>/<name>`，Codex 與 Claude 共用同一個前綴；既有 `codex/` 分支不受影響。
