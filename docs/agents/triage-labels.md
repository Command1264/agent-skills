# Triage labels

| 標準角色          | GitHub label       | 意義                        |
| ----------------- | ------------------ | --------------------------- |
| `needs-triage`    | `needs-triage`     | 等待維護者評估              |
| `needs-info`      | `needs-info`       | 等待補充資訊                |
| `ready-for-agent` | `ready-for-agent`  | 已具備 Agent 自主執行的條件 |
| `ready-for-human` | `ready-for-human`  | 需要由人類實作或處理        |
| `wontfix`         | `wontfix`          | 已決定不處理                |

當 Skill 提到標準 triage 角色時，使用本表對應的 GitHub label。

## 分類 labels

- `type:new-skill`：新增一個可獨立安裝的 Skill。
- `type:enhancement`：改善既有 Skill 行為。
- `type:bug`：可重現的錯誤或回歸。
- `type:docs`：文件工作。
- `type:maintenance`：repository、CI 或維護工作。
- `area:foundation`：共用 repository foundation。
- `area:google-routes`：`google-routes` 專屬工作。
- `area:commute-analyzer`：`commute-analyzer` 專屬工作。

分類 label 不取代 triage 狀態；每個 open Issue 應保有恰好一個目前適用的
triage label。
