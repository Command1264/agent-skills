---
name: commute-analyzer
description: 使用已安裝的 google-routes，將住家與一至多家公司展開為未來工作日的早晚通勤樣本，先離線預覽 request、重試上限、SKU 與確認門檻，再執行路線查詢並產生繁體中文統計報告。當使用者要比較住家到公司、估算平均或每週／四週通勤時間、調整查詢週數或星期幾時使用；單筆路線查詢改用 google-routes。
---

# Commute Analyzer

以 Python 3.11+ 的 `plan` → 使用者確認 → `run` 兩階段 CLI 分析未來預測通勤時間。所有日期展開、
request 計數、統計與私人檔案路徑由 script 決定；Agent 不手算、不改寫已產生的 plan，
也不直接呼叫 Google API。

## 執行流程

1. 執行 `python scripts/commute_analyzer.py capabilities`。這個命令完全離線。
2. 尋找並驗證 `google-routes` v1。搜尋順序與錯誤修復見
   [`references/dependency-resolution.md`](references/dependency-resolution.md)。缺少或不相容時停止；
   不要自動安裝、複製實作或繞過 capabilities。
3. 若私人設定不存在，依 [`schemas/config-v1.schema.json`](schemas/config-v1.schema.json)
   協助使用者在作業系統的私人 config directory 建立。完整住家與公司位置只放在該檔；
   API key 只能放在 `GOOGLE_MAPS_API_KEY`。
4. 依 [`schemas/plan-request-v1.schema.json`](schemas/plan-request-v1.schema.json) 建立 plan request。
   預設為下一個星期一開始的一週、星期一至五、08:00 去程、18:00 回程，並同時取樣
   `TWO_WHEELER` 與 `DRIVE`。使用者可調整一至四週、星期、時間、公司與本機 QPM。
5. 將 plan request 由 stdin 傳給 `python scripts/commute_analyzer.py plan`。`plan` 只執行
   dependency capabilities 檢查，不會查詢 Routes API。將 stdout plan 視為私人資料保存。
6. 向使用者顯示 plan 內的 `plan_id`、日期、request 數、最多 HTTP request 數、模式、
   預估 SKU request 與本機 QPM。執行前請使用者在 Google Cloud Console 確認目前 Routes API
   quota，並把 `rate_limit_qpm` 設為不高於可用額度；提醒本機 QPM 不是 quota 查詢結果或
   最終帳單估價，`429` 只應是例外復原情境。
7. request 數大於 20 時，必須取得使用者對同一個完整 `plan_id` 的明確確認；plan 有任何
   變更或過期都重新執行 `plan`。20 筆以下仍須先顯示預覽，但不要求額外 token。
8. 確認環境中已有 `GOOGLE_MAPS_API_KEY`，再把未修改的 plan 傳給 `run`。超過門檻時加上
   `--confirm-plan-id <完整 plan_id>`。不要在命令、對話或 log 顯示 key。
9. 檢查 exit code 與 JSON `status`。`TWO_WHEELER` 每個必要樣本都成功才可納入排名；
   `degraded`／fallback 或失敗會排除該公司的機車排名。`DRIVE` 不完整只標示為補充資料不完整，
   不影響機車排名。
10. 回報 JSON 精確秒數及繁體中文 Markdown 中的平均、中位數、最短、最長、每日來回、
    每週合計與四週月估算。說明這是未來預測樣本，不是歷史實際通勤紀錄。

完成條件：執行的 plan 與已預覽／確認的 `plan_id` 完全一致；每個樣本都有結果；必要機車
樣本缺失時已 fail-closed；私人報告與 usage ledger 沒有 API key、完整位置或 provider raw response。

## CLI 快速用法

從本 Skill 根目錄執行：

```powershell
python scripts/commute_analyzer.py capabilities
Get-Content plan-request.json | python scripts/commute_analyzer.py plan --config C:\private\config.json > private-plan.json
Get-Content private-plan.json | python scripts/commute_analyzer.py run
```

超過 20 筆時：

```powershell
Get-Content private-plan.json | python scripts/commute_analyzer.py run --confirm-plan-id "sha256:<完整值>"
```

欄位、stdout／stderr、exit code 與輸出路徑見
[`references/cli-contract.md`](references/cli-contract.md)；私人資料規則見
[`references/private-data.md`](references/private-data.md)。可複現的虛構輸入、plan 與結果見
[`examples/config.json`](examples/config.json)、[`examples/plan-request.json`](examples/plan-request.json)、
[`examples/plan.json`](examples/plan.json) 與 [`examples/result.json`](examples/result.json)。

## 停止條件

- 找不到相容的 `google-routes` v1，或其 path／capabilities 與 plan 記錄不同。
- plan request、私人設定或 plan 有未知欄位、型別錯誤、版本不相容或重複 ID。
- plan 的 `plan_id` 不一致、departure 已到期，或超過 20 筆卻沒有完全相同的確認 token。
- 未設定 `GOOGLE_MAPS_API_KEY`、私人輸出無法安全寫入，或 dependency 回傳不相容結果。
- 使用者要求抵達時間反推；v1 僅支援固定出發時間 `fixed_departure`。
