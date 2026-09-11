# 真實 API smoke test

這項測試會產生付費 API request，只在首次發布、HTTP adapter、認證、field mask、
response parser 或 Google contract 變更時執行。

1. 在 repository 外建立私人 query JSON，最多兩筆，且每個 mode 最多一筆；使用不含
   地址或人名的 `request_id`。
2. 在目前 shell 設定 `GOOGLE_MAPS_API_KEY`，不要把值寫進命令歷史或文件。
3. 執行：

```powershell
python scripts/smoke_test.py --confirm-billable-smoke C:\private\routes-smoke.json
```

runner 只輸出版本、整體狀態、request 數、各 request 的 ID、mode、status 與 attempts；
不輸出位置、Place ID、路線時間、API key 或 Google raw response。提交驗收證據前仍要
人工檢查輸出已去識別化。Smoke runner 關閉一般查詢的重試，因此最多兩筆輸入就是
最多兩次實際 HTTP 呼叫。
