---
name: commute-analyzer
description: 使用已安裝的 google-routes，將命名地點或臨時位置組成任意起終點與多站 Commute Journeys，展開未來工作日的去回程樣本，先離線預覽 request、leg、重試上限、SKU 與確認門檻，再查詢並產生繁體中文統計報告。當使用者要比較住家、租屋處、學校、公司或應徵地點，估算平均、每週或四週通勤時間，指定不同去回程或中途停靠點時使用；單筆路線查詢改用 google-routes。
---

# Commute Analyzer

使用 Python 3.11+ 的 `plan` → 使用者確認 → `run` 流程，分析未來 Routes API 預測樣本。
日期展開、Points 解析、request／leg 計數、統計與私人檔案都交給 script；Agent 不手算、不修改 plan，
也不直接呼叫 Google API。

## 執行流程

1. 執行 `python scripts/commute_analyzer.py capabilities`。確認 `google-routes` 提供 schema v2、
   `itinerary_summary`、2–12 Points 與 fixed order；缺少時依
   [`references/dependency-resolution.md`](references/dependency-resolution.md) 停止並提供安裝指令。
2. 執行完全離線的 `config path` 與 `config check`。兩者只輸出安全 metadata；Windows 顯示
   `legacy_windows_appdata_path` 時，依 [`references/private-data.md`](references/private-data.md)
   人工遷移，不自動讀取、複製或搬移。
3. 新設定優先採 [`schemas/config-v2.schema.json`](schemas/config-v2.schema.json)：在 `locations` 保存
   可重用且用途不限的 Named Locations。每個地點使用唯一 id、非地址 label，以及 address 或 place ID。
   既有 config v1 可繼續搭配 request v1 使用；程式只在記憶體中轉換，不改寫私人檔案。
4. 依 [`schemas/plan-request-v2.schema.json`](schemas/plan-request-v2.schema.json) 建立私人 request。
   每個 Journey 分別指定 outbound 與 return；Point 可引用 `location_id`，或提供本次使用的 inline
   label/location。每個方向 2–12 點，保持輸入順序；return 可用完整 Points 或
   `reverse_outbound: true`。config 與 request 必須同為 v1 或同為 v2。
5. 將 request 由 stdin 傳給 `python scripts/commute_analyzer.py plan`。這一步只檢查 dependency
   capabilities，不查詢 API。將 stdout plan 保存於 repository 與 Skill 目錄外，因 plan 含完整位置。
6. 顯示 plan 的 `plan_id`、日期、Journeys、direction point labels、request／leg 數、最大 HTTP
   request、模式、推定 SKU 與本機 QPM。提醒使用者在 Google Cloud Console 確認實際 quota；本機
   QPM 與 SKU 分類不是帳單保證。
7. request 數大於 `confirmation_threshold`（預設 20）時，取得使用者對同一個完整 `plan_id` 的明確
   確認；plan 有任何變更或過期都重新執行 `plan`。門檻以下仍先顯示預覽。
8. 先執行相依 Skill 的 `credentials check`，再將未修改的 plan 傳給 `run`；超過門檻時加上
   `--confirm-plan-id <完整 plan_id>`。`commute-analyzer` 不讀取、傳遞或記錄 API key。
9. 檢查 exit code 與 JSON `status`。只有完整成功的 `TWO_WHEELER` 必要樣本可參與 Journey ranking；
   degraded／fallback 或失敗會排除該 Journey。DRIVE 不完整只標示補充資料不完整。
10. 回報 JSON 與繁體中文 Markdown 的去程、回程、每日來回、每週與四週估算；多站結果逐段顯示
    labels 與時間。說明這是未來預測，不是歷史實際通勤紀錄。

完成條件：執行的 plan 與預覽／確認的 `plan_id` 完全一致；每個 sample 都有可驗證結果；Points 與
legs 依 label、順序及總計一致；私人報告與 ledger 沒有 API key、完整位置、provider point Place ID
或 raw response。

## CLI 快速用法

```powershell
python scripts/commute_analyzer.py capabilities
python scripts/commute_analyzer.py config path
python scripts/commute_analyzer.py config check
Get-Content plan-request.json | python scripts/commute_analyzer.py plan --config C:\private\config.json > private-plan.json
Get-Content private-plan.json | python scripts/commute_analyzer.py run
```

超過確認門檻時：

```powershell
Get-Content private-plan.json | python scripts/commute_analyzer.py run --confirm-plan-id "sha256:<完整值>"
```

欄位、exit code 與輸出見 [`references/cli-contract.md`](references/cli-contract.md)。可重現的多起點、
臨時目的地與學校 waypoint 範例見 [`examples/config-v2.json`](examples/config-v2.json)、
[`examples/plan-request-v2.json`](examples/plan-request-v2.json)、[`examples/plan-v2.json`](examples/plan-v2.json)
與 [`examples/result-v2.json`](examples/result-v2.json)。

首次發布或 provider 邊界改變時，維護者依 [`references/smoke-test.md`](references/smoke-test.md)
執行兩筆、零重試的真實 API smoke；一般分析使用 `run`，不使用發布 runner。

## 停止條件

- 找不到相容的 `google-routes`，或目前 path／capabilities 與 plan 記錄不同。
- config、request 或 plan 有未知欄位、型別錯誤、跨版本、重複 ID／label 或無效 return。
- plan v1、`plan_id` 不一致、departure 已到期，或超過門檻但確認 token 不同。
- provider 的 request IDs、mode、Points、legs、labels 或 totals 與 plan 不一致。
- credential 無效、私人輸出無法安全寫入，或使用者要求尚未支援的 `target_arrival`。
