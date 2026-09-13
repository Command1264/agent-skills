# CLI contract v1.0.0

CLI 使用 Python 3.11+、UTF-8 JSON 與 stdin/stdout。stdout 永遠只有一個 JSON value；
人類可讀診斷只寫 stderr。

## `capabilities`

完全離線，exit `0`。輸出 Skill／CLI 版本、支援命令、預設值及要求的 `google-routes` 能力。

## `plan [--config PATH]`

stdin 是 `plan-request-v1`。未傳 `--config` 時使用預設私人 config path。只會呼叫
`google-routes capabilities`，不會執行 `query` 或發出 Routes API request。

成功輸出不可變的 `plan-v1`，其中 `plan_id` 是排除該欄位後，以排序 key、無多餘空白的
UTF-8 JSON 計算 SHA-256。這是完整 plan 的確認 token，不是密碼學簽章；`run` 仍會嚴格驗證內容。
`rate_limit_qpm` 是傳給 `google-routes` 的本機上限；執行者仍須在 Google Cloud Console
確認實際 quota，避免把 `429` 當作正常節流機制。

## `run [--confirm-plan-id ID] [--output-dir PATH]`

stdin 必須是先前 `plan` 產生且未修改、未到期的 plan。`request_count` 大於 plan 中的
`confirmation_threshold` 時，`--confirm-plan-id` 必須與完整 `plan_id` 相同。執行順序是：

1. 驗證 plan 結構、一致性、雜湊與未來時間。
2. 驗證 plan 記錄的 dependency path 與目前 capabilities。
3. 將 plan 樣本轉為 `google-routes` `summary` query；credential 由 dependency 內部解析。
4. 將 dependency 的去識別化 credential／query 錯誤轉為本 Skill 的結構化失敗。
5. 分析結果，寫入私人報告與 append-only ledger。

`TWO_WHEELER` 只有全部必要樣本皆為 `success` 時才完整；`degraded` 不算必要成功。
查詢超過一週時，`weekly_total_seconds` 是所有完整取樣週合計的每週平均；
`four_week_month_estimate_seconds` 再以該值乘四，不是日曆月實測。

## Exit code

| Code | 意義 |
| --- | --- |
| `0` | 全部樣本成功 |
| `2` | 使用方式、輸入、設定、plan 或 dependency credential／query 錯誤；未執行 query 或沒有可分析結果 |
| `3` | 部分成功或含降級結果；報告仍已產生 |
| `4` | 所有樣本失敗；報告仍已產生 |

錯誤 stdout 格式：

```json
{"schema_version":"1","error":{"code":"ERROR_CODE","path":"$.field","message":"可操作訊息"}}
```

`run` 的成功／部分結果符合 [`../schemas/result-v1.schema.json`](../schemas/result-v1.schema.json)。
