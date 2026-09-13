# google-routes 相依性解析

`commute-analyzer` 可獨立安裝，但執行 `plan` 或 `run` 前必須找到相容的 `google-routes`。
它不會靜默安裝依賴，也不會內嵌或複製 Google adapter。

## 搜尋順序

1. `GOOGLE_ROUTES_SKILL_DIR` 指定的目錄。
2. 與 `commute-analyzer` 相鄰的 `google-routes` 目錄。
3. 目前專案的 `.agents/skills/google-routes`。
4. 使用者目錄的 `.agents/skills/google-routes`。

第一個同時包含 `SKILL.md` 與 `scripts/google_routes.py` 的候選會被選中。plan 的
`dependency.path` 會顯示實際解析路徑，方便稽核。執行 `run` 時會再次檢查同一路徑及
capabilities；路徑或能力改變就拒絕舊 plan。

## 安裝或更新

```powershell
npx skills add Command1264/agent-skills
```

必要能力為：Skill major `2`、CLI contract `2.0.0`、schema `2`、`itinerary_summary` profile、
`DRIVE`／`TWO_WHEELER`，以及 2–12 Points、最多 10 個 stopover intermediates、fixed order 且不支援
optimization。不相容時使用同一命令更新，再重新建立 plan。

`commute-analyzer` 不解析 dependency 的 credential，也不把 API key 放進 subprocess argument
或 environment。請先從解析到的 `google-routes` 目錄執行 `credentials check`；credential
錯誤由 provider Skill fail-closed。
