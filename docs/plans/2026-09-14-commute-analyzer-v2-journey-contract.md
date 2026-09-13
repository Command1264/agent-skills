# commute-analyzer v2 Journey 契約與實作計畫

## 目標與邊界

將 `commute-analyzer` 從固定住家／公司模型提升為以 Commute Journey 為分析單位的
`v2.0.0`：使用者可以保存任意 Named Locations、臨時提供位置、為去程與回程安排不同的固定順序
Points，並繼續取得未來工作日的預測統計、每週與四週估算。

本文件固定 v2 公開 JSON interface、v1 升級策略、資料與成本語意及測試矩陣。第一階段不修改
runtime、正式 schemas、Skill 文件或公開 examples；下列 JSON 是規範性候選資料，只有在對應
schemas、tests 與 runtime 同時完成後才移入 `skills/commute-analyzer/`。

追蹤項目：[Issue #20](https://github.com/Command1264/agent-skills/issues/20)。依賴的
`google-routes v2.1.0` 已提供 query schema v2、`itinerary_summary` 與 2–12 個固定順序 Points。

## 已確認決策

### 一個 v2 執行模型，兩種成對輸入

- `config v2 + plan request v2` 是原生 interface。
- `config v1 + plan request v1` 繼續可用，但先由 v1 Compatibility Adapter 正規化為同一個
  v2 planning model；planner、runner、分析與報告不保留第二條 v1 路徑。
- `v1 + v2` 或 `v2 + v1` 以 `incompatible_input_schema_versions` fail-closed，避免猜測
  `home`、公司與 Named Location 的對應。
- `config check` 接受 v1 與 v2，只回報 schema version、有效性與不含內容的遷移提示；不自動改寫、
  複製或搬移私人設定。
- v2 runtime 不執行既有 plan v1；它在 dependency discovery、credential lookup、API request、report
  或 ledger 寫入前回傳 `legacy_plan_requires_regeneration`，要求重新離線 `plan`。
- 不論輸入版本，新的 Execution Plan 與 Result 一律使用 schema v2；來源版本與 Adapter 名稱寫入
  plan 並納入 `plan_id`。

這讓既有使用者不必立即改寫私人 config，又避免永久維護兩套影響成本確認的 runner。完整取捨見
[ADR 0010](../adr/0010-normalize-v1-inputs-to-v2-journeys.md)。

### 深層 module 與 seam

公開 CLI 仍只有 `capabilities`、`config path`、`config check`、`plan` 與 `run`。複雜度集中在：

1. **Planning Input Normalizer**：嚴格驗證成對輸入，將 v1 或 v2 轉成單一 Normalized Journey
   Collection，隱藏 v1 `home/companies`、Named Location 解析、inline location、return 反轉與預設值。
2. **Execution Plan Builder**：只接受正規化輸入與已驗證 capabilities，展開日期、方向、模式與完整
   Points，計算 request／leg／SKU／重試上限並產生唯一 plan v2。
3. **Plan Runner and Analyzer**：只接受完整且未修改的 plan v2，透過既有 subprocess seam 呼叫
   `google-routes` query v2；正式 Adapter 執行 CLI，測試 Adapter 回傳 itinerary result v2。

外部 CLI interface 是測試面。`google-routes` 是自有、可本機替換的 subprocess dependency，其穩定
CLI 是 port，正式 subprocess 與 mock runner 是兩個實際 Adapters；真正的 True External Google API
留在 provider Skill 後方，consumer 不解析 Google raw response。

## config v2

```json
{
  "schema_version": "2",
  "locations": [
    {
      "id": "home",
      "label": "示例住家",
      "location": {"address": "示例市第一路 1 號"}
    },
    {
      "id": "rental",
      "label": "示例租屋處",
      "location": {"address": "示例市第二路 2 號"}
    },
    {
      "id": "school",
      "label": "示例學校",
      "location": {"place_id": "ChIJExampleSchool"}
    }
  ],
  "utc_offset": "+08:00",
  "outbound_departure_time": "08:00",
  "return_departure_time": "18:00"
}
```

- `locations` 必須存在，可以是空 array，讓全 inline 的臨時計畫仍可執行。
- 每個 Named Location 需要 `id`、`label`、`location`；id 使用既有
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` 且不得重複。
- label 為 1–80 字元，以符合 `google-routes` Point；它用於預覽與私人報告，不送給 provider，
  也不得用完整地址充當 label。
- location 恰好包含非空 `address` 或 `place_id`；未知欄位與兩者並存均拒絕。
- catalog label 可以重複，但同一 direction 展開後的 Point labels 必須唯一，否則 legs 無法無歧義對應。
- `outbound_departure_time`／`return_departure_time` 取代 morning／evening；v1 Adapter 分別映射舊欄位。
- config 路徑、跨 runtime fallback、`COMMUTE_ANALYZER_CONFIG` 與不自動遷移政策維持 v1.1.0。

## plan request v2

```json
{
  "schema_version": "2",
  "weeks": 1,
  "weekdays": [1, 2, 3, 4, 5],
  "travel_modes": ["TWO_WHEELER", "DRIVE"],
  "rate_limit_qpm": 60,
  "journeys": [
    {
      "id": "home-to-candidate",
      "label": "住家到應徵公司",
      "outbound": {
        "points": [
          {"location_id": "home"},
          {"label": "示例應徵公司", "location": {"address": "示例市第三路 3 號"}}
        ]
      },
      "return": {"reverse_outbound": true}
    },
    {
      "id": "rental-via-school",
      "label": "租屋處經學校到應徵公司",
      "outbound": {
        "points": [
          {"location_id": "rental"},
          {"location_id": "school"},
          {"label": "示例應徵公司", "location": {"address": "示例市第三路 3 號"}}
        ]
      },
      "return": {
        "points": [
          {"label": "示例應徵公司", "location": {"address": "示例市第三路 3 號"}},
          {"location_id": "rental"}
        ]
      }
    }
  ]
}
```

沿用 v1 的 `start_date`、`weeks`、`weekdays`、`travel_modes`、`rate_limit_qpm`、
`confirmation_threshold` 與 `schedule_mode: fixed_departure`。時間 override 改名為
`outbound_departure_time`／`return_departure_time`，未提供時使用 config v2 預設。

- `journeys` 至少一筆；每筆需要唯一 id、1–80 字元 label、`outbound` 與 `return`。
- direction 的 `points` 為 2–12 個固定順序 Points，不自動最佳化且不支援 `via`。
- Point 恰好是 `{"location_id":"..."}`，或含 `label`／`location` 的 inline Point；不接受兩種來源並存。
- `location_id` 必須存在。inline location 只存在於私人 request／plan，不寫回 config。
- `return` 恰好包含完整 `points`，或 `{"reverse_outbound":true}`；`false`、並存或皆缺均拒絕。
- reverse 在 planner 內反轉已解析 outbound Points；plan 不保存 shortcut，只保存完整 Points。
- 同一 direction 的 Point labels 必須唯一；Points 可以重訪相同 location。

第一版不加入 request-local location catalog。Agent 可在多個 Journeys 重複同一 inline location，避免新增
第三種 reference scope；若實際使用證明負擔明顯，再以新 schema 評估。

## v1 Compatibility Adapter

Adapter 只接受完整有效的 v1 config 與 request，並維持既有 default／override：

| v1 來源 | v2 正規化結果 |
| --- | --- |
| `home` | 每個 Journey outbound 第一點；label/location 原樣保留 |
| `companies[]`／`additional_companies[]` | 各形成一個 Journey；id 用 company id，label 用 company name |
| outbound | `[home, company]` |
| return | `[company, home]`，在 plan 完整展開 |
| `morning_departure_time` | `outbound_departure_time` |
| `evening_departure_time` | `return_departure_time` |
| schedule、mode、QPM、門檻 | 保持 v1 驗證與預設 |

Adapter plan metadata：

```json
{
  "input_compatibility": {
    "config_schema_version": "1",
    "plan_request_schema_version": "1",
    "adapter": "v1_to_v2"
  }
}
```

原生 v2 的 `adapter` 為 `null`。metadata 與展開 Points 均納入 `plan_id`。v1 的 duplicate id、unknown
fields 與 location 錯誤仍使用精確舊 JSON path。因 v1 的 home label／company name 原本沒有 80 字元
上限，也允許 route 內重複 label，Adapter 必須在原始欄位 path 回傳可操作錯誤；不得截斷、改名或猜測
leg 對應。除此之外，完整有效且符合 v2 Point label 限制的 v1 inputs 均可產生 plan v2。

### 人工遷移

文件提供對照，但 runtime 不寫檔：將 home／companies 轉成由使用者選定 id 的 Named Locations；
將 morning／evening 改名為 outbound／return；在 request v2 明確建立 Journeys；最後執行
`config check` 與完全離線 `plan`，人工確認 preview 與新 `plan_id`。v1 config 可繼續使用。

## Execution Plan v2

plan v2 是 `run` 唯一接受的 interface，包含：

- `schema_version: "2"`、`plan_contract_version: "2.0.0"`、created time 與 plan id。
- `input_compatibility`，揭露兩個來源 schema 與 Adapter。
- dependency 固定要求 google-routes major 2、CLI `2.0.0`、schema `2`、
  `itinerary_summary`、2–12 Points、最多 10 intermediates、fixed order 與所需 modes。
- schedule 使用 outbound／return times。
- preview 使用 `journey_count` 取代 company count，並包含所有 Journey labels、每個 direction 的
  `point_labels`、`point_count`、`intermediate_count` 與 `leg_count`。
- samples 每項包含 request id、journey id／label、日期、direction、完整 resolved Points、mode、
  departure time 與 `expected_leg_count`；不再保存 company/origin/destination 專屬欄位。

以下節錄顯示 `reverse_outbound` 在不可變 plan 中已展開，不是完整公開 example：

```json
{
  "schema_version": "2",
  "plan_contract_version": "2.0.0",
  "input_compatibility": {
    "config_schema_version": "2",
    "plan_request_schema_version": "2",
    "adapter": null
  },
  "preview": {
    "journey_count": 2,
    "request_count": 8,
    "planned_leg_count": 10,
    "retry_limit": 2,
    "maximum_http_requests": 24,
    "estimated_sku_requests": {
      "routes_compute_pro": 4,
      "routes_compute_enterprise": 4
    }
  },
  "samples": [
    {
      "request_id": "home-to-candidate.20990105.outbound.two-wheeler",
      "journey_id": "home-to-candidate",
      "journey_label": "住家到應徵公司",
      "date": "2099-01-05",
      "direction": "outbound",
      "points": [
        {"label": "示例住家", "location": {"address": "示例市第一路 1 號"}},
        {"label": "示例應徵公司", "location": {"address": "示例市第三路 3 號"}}
      ],
      "travel_mode": "TWO_WHEELER",
      "departure_time": "2099-01-05T08:00:00+08:00",
      "expected_leg_count": 1
    },
    {
      "request_id": "home-to-candidate.20990105.return.two-wheeler",
      "journey_id": "home-to-candidate",
      "journey_label": "住家到應徵公司",
      "date": "2099-01-05",
      "direction": "return",
      "points": [
        {"label": "示例應徵公司", "location": {"address": "示例市第三路 3 號"}},
        {"label": "示例住家", "location": {"address": "示例市第一路 1 號"}}
      ],
      "travel_mode": "TWO_WHEELER",
      "departure_time": "2099-01-05T18:00:00+08:00",
      "expected_leg_count": 1
    }
  ],
  "plan_id": "sha256:<由完整 plan 計算的 64 位十六進位值>"
}
```

完整 plan 另含 created time、dependency、schedule、完整 preview、全部 Journeys／dates／modes 的
samples；實作後的公開 example 必須是真實 planner 可重現的完整 JSON，不使用上述 placeholder。

計數規則：

- `request_count = journey 數 × 日期數 × 2 directions × mode 數`；每個 sample 是一筆 Compute Routes query。
- `expected_leg_count = points.length - 1`；`planned_leg_count` 是所有 samples 的 legs 總和，leg 不是 API request。
- `maximum_http_requests = request_count × (retry_limit + 1)`。
- DRIVE 計入推定 Pro，TWO_WHEELER 計入推定 Enterprise；這不是報價或帳單保證。
- reverse 展開、dependency、preview、schedule 與完整私人 Points 全部納入 `plan_id`。

preview 可顯示非地址 labels，不顯示 address、place ID 或 provider response。Plan 本身含執行位置，必須
視為私人檔案，不得貼到公開 Issue／PR。

## `run` 與 Result v2

`run` 先驗證 plan v2 schema、一致性、hash、期限、確認門檻及目前 capabilities，再將 samples 映射為
單一 `google-routes` query v2 envelope。缺少 itinerary 能力時在 credential／API 前 fail-closed；
`commute-analyzer` 不讀取或傳遞 Google key。

Result v2 將 `companies` 改成 `journeys`，每個 Journey 保留：

- journey id／label、ranking eligibility、排除原因與各 mode 結果。
- outbound、return、daily round trip 的平均、中位數、最短、最長。
- 每週平均總時間與乘四的四週月估算，不宣稱歷史真實平均。
- 成功／degraded sample 的 route total 與 legs：from/to labels、距離、含交通與靜態時間。
- 不保存 input address、input place ID 或 provider point place IDs；私人報告只保留 labels 與統計。

以下結果節錄展示 Journey 與分段資料的最小形狀；它刻意不含 input location 或 provider point place ID：

```json
{
  "schema_version": "2",
  "analysis_contract_version": "2.0.0",
  "status": "success",
  "journeys": [
    {
      "journey_id": "rental-via-school",
      "journey_label": "租屋處經學校到應徵公司",
      "ranking_eligible": true,
      "ranking_exclusion_reasons": [],
      "modes": {
        "TWO_WHEELER": {
          "complete": true,
          "statistics": {
            "outbound": {
              "average_seconds": 1200,
              "median_seconds": 1200,
              "minimum_seconds": 1200,
              "maximum_seconds": 1200
            },
            "return": {
              "average_seconds": 900,
              "median_seconds": 900,
              "minimum_seconds": 900,
              "maximum_seconds": 900
            },
            "daily_round_trip": {
              "average_seconds": 2100,
              "median_seconds": 2100,
              "minimum_seconds": 2100,
              "maximum_seconds": 2100
            }
          },
          "weekly_total_seconds": 10500,
          "four_week_month_estimate_seconds": 42000,
          "samples": [
            {
              "request_id": "rental-via-school.20990105.outbound.two-wheeler",
              "date": "2099-01-05",
              "direction": "outbound",
              "travel_mode": "TWO_WHEELER",
              "status": "success",
              "attempts": 1,
              "distance_meters": 12000,
              "duration_seconds": 1200,
              "static_duration_seconds": 1050,
              "legs": [
                {
                  "from_label": "示例租屋處",
                  "to_label": "示例學校",
                  "distance_meters": 4000,
                  "duration_seconds": 450,
                  "static_duration_seconds": 400
                },
                {
                  "from_label": "示例學校",
                  "to_label": "示例應徵公司",
                  "distance_meters": 8000,
                  "duration_seconds": 750,
                  "static_duration_seconds": 650
                }
              ]
            }
          ]
        }
      }
    }
  ]
}
```

完整 result 仍包含 plan id、generated time、dependency path、request summary、全部 modes／samples、
ranking 與私人 output paths；正式 schema 與 example 必須補齊並禁止未知欄位。

完整性沿用 v1：每個 Journey／mode 的全部日期與 directions 都是必要 samples，degraded 不算完整。
TWO_WHEELER 完整時才可參與 Journey Ranking；未要求機車時 ranking 為空。DRIVE 不完整不影響完整的
機車排名，但須標示。Exit codes 維持 `0`、`2`、`3`、`4` 原語意。

ledger 仍只保存時間、plan id、預計／實際 request、成功／失敗／degraded／重試、mode 與推定 SKU；
不得加入 Journey／Point labels、location、route/leg 時間或 provider response。報告檔名只用日期與
plan-id-derived report id。

## capabilities v2

`capabilities` 完全離線，使用分類版本欄位取代有歧義的單一 schema list：

```json
{
  "skill_name": "commute-analyzer",
  "skill_version": "2.0.0",
  "cli_contract_version": "2.0.0",
  "config_schema_versions": ["1", "2"],
  "plan_request_schema_versions": ["1", "2"],
  "plan_schema_versions": ["2"],
  "result_schema_versions": ["2"],
  "required_google_routes": {
    "skill_major": 2,
    "cli_contract_version": "2.0.0",
    "schema_version": "2",
    "output_profile": "itinerary_summary",
    "minimum_points": 2,
    "maximum_points": 12,
    "maximum_intermediate_waypoints": 10,
    "waypoint_order": "fixed"
  }
}
```

commands、weeks、weekdays、modes、QPM 與門檻 defaults 維持現有欄位。

## 錯誤模型

| code | 條件 | 修復 |
| --- | --- | --- |
| `incompatible_input_schema_versions` | config/request 不是同為 v1 或 v2 | 改用成對版本後重跑 plan |
| `unknown_location_id` | Point 引用不存在的 catalog id | 修正 id 或使用 inline location |
| `duplicate_location_id` | config locations id 重複 | 保留唯一 id |
| `duplicate_journey_id` | request journeys id 重複 | 保留唯一 id |
| `duplicate_point_label` | direction resolved labels 重複 | 使用可區分 labels |
| `legacy_point_label_incompatible` | v1 home label／company name 超過 80 字元 | 縮短私人 label 或遷移至 v2 |
| `invalid_return_definition` | return 同時或皆未提供 points/reverse | 只選一種 |
| `legacy_plan_requires_regeneration` | `run` 收到 plan v1 | 以原 inputs 重新離線 plan |
| `incompatible_itinerary_dependency` | google-routes 缺少 v2 itinerary 能力 | 更新相依 Skill |
| `dependency_leg_mismatch` | 成功結果 legs 數或 labels 不符 plan | 拒絕該 sample，不猜測對應 |

錯誤不得包含 address、place ID、API key、raw response 或整份私人輸入。

## 測試矩陣

| 層級 | 必須固定的行為 |
| --- | --- |
| Schema | config v2 空／多地點、location one-of、id/label limits、unknown fields、duplicate ids |
| Schema | request v2 saved/inline、2/3/12 Points、13 拒絕、return one-of、跨版本拒絕 |
| Adapter | v1 home、companies、additional companies、defaults、override 與錯誤 path 正確轉成 v2 |
| Adapter | v1 過長或 route 內重複 labels 以原始 path 拒絕，不截斷、不自動改名 |
| Plan | 完全離線；不同已保存起點可比較同一重複 inline 公司；學校 waypoint 保持順序 |
| Plan | outbound/return 可不同；reverse 展開並影響 plan id；任何有效內容變更使 hash 改變 |
| Preview | request、leg、最大 HTTP、mode/SKU 數學正確；labels 可見但 location/place ID 不出現 |
| Dependency | 缺 schema v2、profile、fixed order、limits 或 mode 時在 API 前 fail-closed |
| Run | plan v1、過期／竄改 plan v2、錯誤確認 id 均在 query 與輸出寫入前停止 |
| Mapping | 每 sample 一筆 query v2；Points、順序、mode、time、QPM 完全符合 plan |
| Result | totals、legs、direction/daily/weekly/four-week 統計與 TWO_WHEELER ranking 正確 |
| Failure | error/degraded 的完整性、排除、exit code 與成功資料保留正確 |
| Privacy | stdout/stderr/exception/preview/ledger/檔名無 canary location/API key；報告無 location |
| Files | v1 config 只讀；inline 不寫回；report/ledger 只寫私人 data directory |
| Examples | config/request/plan/result v2 虛構資料符合 schemas 並可由 runtime 重現 |
| E2E | mock 完成「兩起點比較同一臨時公司」與「去程經學校、回程直達」 |
| Regression | v1 inputs 產生 plan v2；path/check、門檻、重試與 cross-runtime 路徑不回歸 |

測試從 CLI 與公開 Python interface 驗證可觀察結果，不鎖定 Normalizer 私有資料。CI 使用 temporary
HOME 與 mock dependency，不讀真實 config／credential、不呼叫 API。

## 實作順序與停止條件

### 2A：Schemas、examples 與 RED tests

新增四種 v2 schemas／虛構 examples，先固定 compatibility matrix、return one-of、Point limits、preview
math、plan v1 拒絕及 privacy canaries。若 schema 必須靠寬鬆 unknown fields 或隱式角色才能覆蓋兩個
critical paths，停止並回到 Issue 確認。

### 2B：Normalizer 與離線 planner

實作單一 Normalizer／Plan Builder，更新 capabilities、config check、plan 與 v1 Adapter。若需要第二個
planner／runner，或必須自動讀寫私人 config 才能相容，停止並重評 seam。

### 2C：Runner、分析與私人產物

映射 query v2、驗證 itinerary legs、泛化 Journey result/ranking，完成 mock E2E、regression、validator、
compile、diff 與 privacy scan。若 Points/legs 不能與 plan labels 一致對應，或一般輸出／ledger 洩漏
location，不得產生報告或進入 smoke。

### 3：整合 smoke 與發布

另行準備公開地標、兩種 mode 各一筆、零重試且硬上限兩筆的 commute v2 → google-routes v2 waypoint
smoke plan，取得精確 hash 核准後才執行。發布依 task PR → `develop` → release PR → `main` → tag／
Release → `develop` 回流進行，每個 remote write 另取授權。

## 文件與實作影響

後續預計更新 `skills/commute-analyzer/` 的 SKILL、CHANGELOG、references、四種 schemas、examples、evals、
scripts；相關 tests、repository validator、README、skills README、CONTEXT 與必要 ADR。不修改
`google-routes` runtime；若 v2.1.0 interface 不足，另開 provider Issue，不在 consumer 複製實作。

第一階段只以本文件、domain glossary、ADR、repository validator、Markdown links 與 diff check 驗收。
本規劃不授權 runtime 實作、讀取或遷移私人資料、API request、push、PR、merge、tag 或 Release。
