# 真實 API 發布 smoke

這項測試只供首次發布，或 `google-routes` 的 HTTP adapter、認證、field mask、response parser、
provider contract 改變後使用。一般通勤分析仍使用 `plan` → 確認 → `run`。

## 驗證範圍

runner 先離線驗證不可變 execution plan、目前解析到的 `google-routes` path 與 capabilities，
再從 plan 固定選取第一筆 `TWO_WHEELER` 與第一筆 `DRIVE` 樣本。它把兩筆私人 query 暫存在
作業系統 temp directory，委派給 `google-routes` 的發布 smoke runner，完成後刪除暫存檔。

每個模式都關閉重試，因此程式硬上限為兩次實際 HTTP request。這兩筆不足以形成完整的
早晚通勤樣本集合；runner 不產生通勤排名、報告或 usage ledger，也不宣稱驗證正式統計結果。
完整分析與報告由不呼叫外部服務的 mock integration tests 驗證。

## 執行

1. 在 repository 與 Skill 目錄外保存由目前版本 `plan` 產生的私人 execution plan。plan 必須
   同時包含 `TWO_WHEELER` 與 `DRIVE`，而且 dependency path 與目前安裝位置一致。
2. 在 Google Cloud Console 確認 Routes API quota、billing 與受限 API key；不要用 `429`
   測試節流。從解析到的 `google-routes` 目錄執行 `credentials check`，不得使用舊環境變數。
3. 從 `commute-analyzer` Skill 根目錄執行：

```powershell
python scripts/smoke_test.py --confirm-billable-smoke C:\private\commute-plan.json
```

缺少 `--confirm-billable-smoke` 時，runner 會在讀取 plan 或執行 dependency 前停止。執行前
`stderr` 會再次顯示兩種模式、最多兩次 HTTP request 與零重試。

## 證據與驗收

stdout 只輸出 `commute-analyzer`／`google-routes` 版本、整體狀態、request 數、硬上限、
每種模式的狀態與 attempts。它不輸出 plan ID、request ID、完整位置、Place ID、路線時間、
API key、暫存路徑或 provider raw response。提交驗收證據前仍要人工檢查輸出已去識別化。

- exit `0`：兩筆皆成功。
- exit `3`：含 fallback 或部分成功，不能當作完整成功證據。
- exit `4`：兩筆皆失敗。
- exit `2`：本機輸入、相依、key 或 smoke 證據錯誤；不得當作外部服務驗證。

任何 result 的 `attempts` 不是 `1`，或 dependency 證據與兩筆固定模式不一致，runner 都會
fail-closed，拒絕輸出成功證據。
