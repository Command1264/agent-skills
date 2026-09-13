# Google Routes CLI contract v2

## Commands

- `python scripts/google_routes.py capabilities`：不讀取 API key、不呼叫網路。
- `python scripts/google_routes.py credentials path`：只回報預設 secret file 路徑。
- `python scripts/google_routes.py credentials check`：離線驗證 secret file 與舊環境變數。
- `python scripts/google_routes.py credentials set`：從互動式隱藏輸入安全建立或更新 secret file。
- `python scripts/google_routes.py query`：由 stdin 讀取一個 query envelope，stdout
  僅輸出一個 JSON envelope，診斷只寫入 stderr。

Credential commands 與 `capabilities` 都不呼叫 Google API。`credentials set` 不接受
`--api-key`、stdin key 欄位或自訂 credential path；完整契約見
[`credentials.md`](credentials.md)。

## Query envelope

直接起終點輸入遵循 [`../schemas/query-v1.schema.json`](../schemas/query-v1.schema.json)，
並使用 `summary` profile。多站輸入遵循
[`../schemas/query-v2.schema.json`](../schemas/query-v2.schema.json)，使用
`itinerary_summary` profile，以 2–12 個 ordered points 表示起點、0–10 個固定順序 stopovers
與終點。每個 location 必須且只能使用 `address` 或 `place_id`；label 只供本機結果對應，
不送給 Google。所有 object 都拒絕未知欄位。

`DRIVE` 固定對應 `TRAFFIC_AWARE_OPTIMAL` 與 `BEST_GUESS`；`TWO_WHEELER` 固定對應
`TRAFFIC_AWARE`，不傳送 `trafficModel`。兩者都只請求主要建議路線。

## Result envelope

`summary` 輸出遵循 [`../schemas/result-v1.schema.json`](../schemas/result-v1.schema.json)；
`itinerary_summary` 遵循 [`../schemas/result-v2.schema.json`](../schemas/result-v2.schema.json)，
另提供不含地址的 point label／Place ID 與逐段 distance／duration。批次狀態：

- `success`：所有項目完整成功。
- `degraded`：沒有失敗，但至少一項含 Google `fallbackInfo`。
- `partial_success`：至少一項成功或降級，且至少一項失敗。
- `failure`：所有項目失敗。

每筆結果保留 `request_id`。兩個 profile 都不含 polyline、steps、viewport、route token、
完整地址或完整 provider response。

## Exit codes

| Code | 意義 |
| ---: | --- |
| `0` | 完整成功或 `capabilities` 成功 |
| `2` | CLI 用法、JSON、schema 或 credential 錯誤 |
| `3` | 降級或部分成功 |
| `4` | 所有 route requests 在有限重試後失敗 |

HTTP `429`、`5xx` 與網路錯誤最多重試兩次；其他 `4xx` 不重試。若回應含
`Retry-After`，等待時間優先採用該值。
