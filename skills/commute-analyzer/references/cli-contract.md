# CLI contract v2.0.0

CLI 使用 Python 3.11+、UTF-8 JSON 與 stdin/stdout。stdout 永遠只有一個 JSON value；人類可讀
診斷只寫 stderr。`commute-analyzer` 不讀取或傳遞 Google API key。

## `capabilities`

完全離線，exit `0`。分開回報 config、plan request、plan 與 result 支援版本，並聲明要求
`google-routes` schema v2、`itinerary_summary`、2–12 Points、最多 10 個 intermediates 與 fixed order。

## `config path`

完全離線，exit `0`。只輸出目前選用的 config path、跨 runtime 預設路徑、來源、存在狀態及
Windows 舊 AppData 遷移提示，不讀取設定內容。解析優先序為 `COMMUTE_ANALYZER_CONFIG`、存在的新
預設 config、目前 runtime 可見的舊 Windows AppData config，最後是尚未建立的新預設路徑。

## `config check`

完全離線。接受 config v1 或 v2，嚴格驗證後只增加 `content_schema_version` 與不含內容的
`schema_migration` metadata。v1 仍可使用；`recommended: true` 只表示建議人工遷移，程式不會改寫、
複製或搬移私人設定。找不到檔案或內容無效時 exit `2`。

## `plan [--config PATH]`

stdin 必須是 `plan-request-v1` 或 `plan-request-v2`，且與 config 使用相同 schema version：

- v1 + v1 經 Compatibility Adapter 正規化為 Journeys。
- v2 + v2 解析 Named Locations、inline locations、outbound 及 return Points。
- 跨版本組合以 `INCOMPATIBLE_INPUT_SCHEMA_VERSIONS` 拒絕。

`plan` 只呼叫 `google-routes capabilities`，不讀取 credential、不執行 `query`。兩種輸入都輸出唯一的
plan v2；`reverse_outbound` 已展開為完整 Points。`plan_id` 是排除該欄位後，以排序 key、無多餘空白
的 UTF-8 JSON 計算 SHA-256。Plan 含完整私人位置，必須保存在 repository 與 Skill 目錄外。

Preview 分開顯示 Journey 數、Compute Routes request 數、route leg 數、最大 HTTP request、推定 SKU、
labels 與本機 QPM；不顯示 address 或 Place ID。本機 QPM 不是 Google Cloud quota 或帳單保證。

## `run [--confirm-plan-id ID] [--output-dir PATH]`

stdin 必須是未修改、未過期的 plan v2。plan v1 會在 dependency discovery、credential、API request 與
輸出寫入前以 `LEGACY_PLAN_REQUIRES_REGENERATION` 拒絕。request 數大於
`confirmation_threshold` 時，`--confirm-plan-id` 必須等於完整 `plan_id`。

執行順序：

1. 驗證 plan schema、hash、期限、sample matrix、預覽數學及確認 token。
2. 重新解析並比對 `google-routes` path 與 itinerary capabilities。
3. 每個 sample 映射為一筆 query v2 request，保持完整 Points 順序、mode、departure time 與 QPM。
4. 驗證 result 的 request IDs、Points、legs、labels、totals 與 plan 一致；不相容時不猜測對應。
5. 以 Journey 為單位計算方向、每日來回、每週與四週估算，寫入私人 JSON／Markdown 與 usage ledger。

只有 `success` 樣本計入完整性與統計；`degraded`／fallback 保留但不算必要成功。`TWO_WHEELER` 全部必要
樣本成功的 Journey 才參與排名；未要求機車時 ranking 為空。多週結果先除以取樣週數，再乘四產生
四週估算。

報告保存 labels、legs 與統計，不保存 input address、input Place ID、provider point Place ID 或 raw
response。Ledger 只保存執行時間、plan ID、request／retry／狀態、modes 與推定 SKU。

## Exit code

| Code | 意義 |
| ---: | --- |
| `0` | 全部樣本成功 |
| `2` | 使用方式、輸入、設定、plan、dependency 或 credential／query contract 錯誤 |
| `3` | 至少一筆成功或降級，且結果不是全部成功 |
| `4` | 所有樣本失敗；報告仍已產生 |

錯誤 stdout 是帶 `error.code`、`error.path` 與去識別化 `error.message` 的 JSON。成功與部分結果遵循
[`../schemas/result-v2.schema.json`](../schemas/result-v2.schema.json)。
