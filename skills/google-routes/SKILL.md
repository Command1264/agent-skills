---
name: google-routes
description: 使用 Google Routes API 查詢明確起點、終點、固定順序停靠點與未來出發時間的汽車或機車路線，並輸出穩定、最小化的總計或分段結果。當使用者需要單筆或批次 Route API 查詢、任意端點、多站路線、交通時間、距離、交通感知預測，或其他 Skill 需要路線查詢能力時使用；需要工作日展開、命名地點、平均通勤或行程排序時改用 commute-analyzer。
---

# Google Routes

以帶版本的 JSON CLI 執行可重現的 Compute Routes 查詢。CLI 擁有輸入驗證、
Google request mapping、主動節流、有限重試與 response 正規化；Agent 不自行拼接
HTTP request，也不解析 Google 原始 response。

## 執行流程

1. 確認使用者提供每筆查詢的起點、終點、`DRIVE` 或 `TWO_WHEELER`，以及包含
   UTC offset 的未來 `departure_time`。位置可使用 `address` 或 `place_id`，優先沿用
   使用者已有的 Place ID。多站路線另確認依序排列的停靠點與每一點的非敏感 label。
2. 從本 Skill 目錄執行 `python scripts/google_routes.py capabilities`。若 Python 低於
   3.11、contract、schema、mode 或 profile 不相容，停止並說明不相容項目。
3. 執行 `python scripts/google_routes.py credentials check`。若 secret file 尚未建立，請使用者在
   自己的終端執行 `python scripts/google_routes.py credentials set`；不要要求使用者把 key 貼進
   對話、命令參數、Issue 或一般 log。格式、路徑與遷移方式見
   [`references/credentials.md`](references/credentials.md)。
4. 直接起終點使用 [`schemas/query-v1.schema.json`](schemas/query-v1.schema.json) 與
   `summary`；含命名 Points 或中途停靠點時，使用
   [`schemas/query-v2.schema.json`](schemas/query-v2.schema.json) 與 `itinerary_summary`。
   query v2 每條路線必須有 2–12 個 ordered points，第一點是起點、最後一點是終點，
   中間最多 10 點且全部是固定順序 stopover。`rate_limit_qpm` 預設為 `60`。
5. 在任何外部呼叫前顯示 request 數、交通模式、profile、每條路線的中途點數、最多兩次重試、
   推定 SKU 與本機 QPM。`DRIVE` 目前推定為 Compute Routes Pro，`TWO_WHEELER` 推定為
   Compute Routes Enterprise；仍以使用者當下的 Cloud Console 為準。
6. 正常 request 數不超過 20 時，在顯示預覽後執行；超過 20 時，先取得使用者對
   該批次內容的明確確認。輸入改變後重新預覽與確認。
7. 將 JSON 由 stdin 傳給 `python scripts/google_routes.py query`。保存 stdout 的 JSON
   時使用使用者指定的位置；未指定時不要在 repository 建立結果檔。
8. 依 exit code 與每筆 `request_id` 檢查結果。`degraded` 的 fallback 路線應保留並
   清楚標示，但不得描述成完整成功；批次中的成功項目不因其他項目失敗而丟棄。
9. 向使用者呈現距離、含交通時間、靜態時間、warnings、fallback 與 Place ID。
   `itinerary_summary` 另依 ordered point labels 呈現每段 leg。預設不重述完整地址，
   不輸出 API key 或 provider raw response。

完成條件：每個 request 都有同一 `request_id` 的結構化結果，成功、降級與失敗均已
分開說明，且所有付費呼叫都在已預覽的批次範圍內。

## CLI

從 Skill 根目錄執行：

```powershell
python scripts/google_routes.py capabilities
python scripts/google_routes.py credentials path
python scripts/google_routes.py credentials check
Get-Content request.json | python scripts/google_routes.py query
```

跨平台 shell 可使用等價的 stdin pipe。完整欄位與 exit code 見
[`references/cli-contract.md`](references/cli-contract.md)，可從
[`examples/query.json`](examples/query.json) 或
[`examples/itinerary-query.json`](examples/itinerary-query.json) 建立輸入。

## Google Cloud 前置

真實查詢需要使用者自己的 Google Cloud project：

- 已啟用 billing 與 Routes API。
- key 限制為 Routes API；適合時再加上來源 IP application restriction。
- key 只保存於 `google-routes` v2 的使用者層級 TOML secret file；不支援環境變數 fallback。
- 由 Cloud Console 檢查實際 quota、費用與告警；本 Skill 的 60 QPM 只是本機上限。

首次發布或 provider contract 疑似改變時，先依
[`references/provider-contract.md`](references/provider-contract.md) 重新查閱官方文件，
不要把本文件記錄的 quota 或欄位當成永久不變。

本機 smoke test 僅供首次發布或 adapter／provider contract 變更時使用。準備含一筆
`TWO_WHEELER`、一筆 `DRIVE` 的私人輸入檔後，閱讀
[`references/smoke-test.md`](references/smoke-test.md)；不要把該檔或輸出加入 Git。

## 停止條件

- 輸入缺欄位、型別錯誤、未知欄位、重複 `request_id` 或 schema 不相容。
- itinerary 少於 2 點、超過 12 點，或要求自動最佳化、pass-through `via` 或其他未支援
  waypoint modifier。
- `departure_time` 不是含明確 offset 的未來時間。
- secret file 缺少、無效、權限不安全、仍存在舊 `GOOGLE_MAPS_API_KEY`，或 endpoint 不是
  本 Skill 固定的 Google Routes HTTPS endpoint。
- 超過 20 筆但尚未取得相同批次內容的明確確認。
- 真實 smoke 輸入超過兩筆、同模式超過一筆，或沒有明確 opt-in flag。
