# 參與貢獻

感謝你協助改善這個 Agent Skill 庫。本專案以易用性、可重現性、隱私與誠實的
驗證邊界為優先。

## 開始前

1. 使用對應的繁體中文 GitHub Issue Form 建立或尋找 Issue。
2. 不要在 Issue、PR、測試資料或 log 貼出 API key、完整住家地址、私人設定或
   未去識別的外部 API response。
3. 一般工作從 `develop` 建立 task branch，PR 目標為 `develop`；`main` 只接受
   經驗收的穩定發布整合。
4. 一個變更維持單一目的，不混入無關重構或 dependency upgrade。

## Skill 內容

- 每個 Skill 位於 `skills/<skill-name>/`，名稱使用 kebab-case。
- `SKILL.md` 應說清楚觸發條件、停止條件、輸入、輸出與可驗證流程。
- 面向使用者的權威文件使用繁體中文；技術識別符與 API 名稱保留原文。
- 不得提交私人資料、secret 或依賴個人電腦絕對路徑的範例。
- 外部 Skill 相依性必須可偵測、不相容時 fail-closed，且不得靜默安裝。

## 驗證

在送出 PR 前執行：

```powershell
python scripts/validate_repository.py
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
```

需要真實外部 API 的 smoke test 不在 CI 執行，必須是明確 opt-in、有限請求，
並在提交證據前移除位置與 secret。

## Commit 與 PR

Commit 使用 Conventional Commits 類型：`feat`、`fix`、`refactor`、`docs`、
`test`、`chore`、`perf`、`ci`。PR 應連結 Issue，列出變更、驗證結果及尚未驗證
的限制。維護者驗收前不得把「CI 通過」描述為正式發布完成。
