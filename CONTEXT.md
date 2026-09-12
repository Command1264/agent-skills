# 個人 Agent Skill 庫

本 repository 收錄可公開使用、可重現安裝與驗證的 Agent Skills。個人地址與偏好等私人資料不屬於公開 Skill 內容，應保存在本機私人設定中。

## 路線與通勤

**`google-routes`（路線查詢 Skill）**：
封裝 Google Routes API 的基礎能力，負責驗證起點、終點、交通模式與出發時間，並將 API 回應轉換成穩定的結構化結果。它不理解公司、上班或求職等情境。
_避免使用_：平均通勤 Skill、公司通勤 Skill

**`commute-analyzer`（平均通勤 Skill）**：
組合 `google-routes`，依指定日期範圍、星期與早晚出發時間建立多筆預測樣本，再計算住家與公司之間的通勤統計。第一版支援單一公司分析與多公司批次比較。它可以獨立透過 `npx skills add` 安裝，但執行前必須確認 `google-routes` 已安裝；找不到時拒絕執行並提供安裝指引。
_避免使用_：Route API Skill、歷史通勤 Skill

**執行期 Skill 相依性（Runtime Skill Dependency）**：
某個 Skill 可以獨立安裝，但必須依賴另一個已安裝的 Skill 才能執行。相依 Skill 缺少時應採 fail-closed，說明缺少的 Skill 與標準 `npx skills add` 安裝方式；不得靜默自動安裝，也不得複製相依 Skill 的實作作為備援。
_避免使用_：自動安裝、內嵌相依性、可選相依性

**Skill CLI 契約（Skill CLI Contract）**：
由 Skill 自己擁有、接受 JSON 輸入並輸出 JSON 的 Python 命令列介面。上層 Skill 透過這項穩定契約組合下層能力，不解析下層的自然語言輸出，也不直接依賴 Google 原始 response。
_避免使用_：Agent 對話契約、Python import 契約、Google response 契約

**相依 Skill 解析（Dependency Skill Resolution）**：
`commute-analyzer` 尋找 `google-routes` 的程序。依序檢查 `GOOGLE_ROUTES_SKILL_DIR`、自身安裝位置的兄弟目錄、目前專案的 `.agents/skills/google-routes`，最後檢查使用者層級的 `~/.agents/skills/google-routes`；執行結果必須揭露實際採用的路徑。
_避免使用_：自動安裝、任意全磁碟搜尋、隱藏相依來源

**Skill 能力描述（Skill Capabilities）**：
Skill CLI 透過不呼叫外部服務的 `capabilities` 命令，回報自身 Skill version、CLI contract version、支援的 schema versions、交通模式與 output profiles。上層 Skill 必須先驗證能力相容性，不得只以目錄存在推定可用。
_避免使用_：安裝狀態、API 可用性、隱含版本相容

**Skill 發布版本（Skill Release Version）**：
單一 Skill 的獨立 SemVer，記錄於該 Skill 的 `CHANGELOG.md`，並以 `<skill-name>-v<version>` Git tag 發布。Tag 必須指向 `main` 上通過 release gate 的 commit；`develop` 版本只供開發與驗收。
_避免使用_：repository 共用版本、develop 最新版、未驗收 tag

**預測通勤樣本（Predictive Commute Sample）**：
針對一組起點、終點、交通模式及未來出發時間取得的一次 Routes API 預測結果。它不是使用者過去實際通勤的紀錄。
_避免使用_：歷史樣本、實際通勤紀錄

**預測通勤時間（Predictive Commute Time）**：
由多筆預測通勤樣本統計出的通勤時間估計值。對外呈現時必須保留「預測」語意，不得宣稱為歷史真實平均。
_避免使用_：真實平均交通時間、過去四週平均

**通勤設定檔（Commute Profile）**：
保存在本機的私人設定，包含住家位置、預設工作日、出發時間、時區與交通模式。通勤設定檔不得提交至公開 repository。
_避免使用_：公開預設值、Skill 內建住家地址

**一週預測取樣（One-week Predictive Sampling）**：
從 `start_date` 起選取 `weeks` 範圍內指定的 `weekdays`，針對每天的早晚出發時間建立預測通勤樣本。`start_date` 預設為下一個星期一、`weeks` 預設為一週、`weekdays` 預設為週一至週五；第一版不自動排除國定假日，所有選定日期共用一組早晚出發時間。
_避免使用_：四週實測、月交通紀錄

**月通勤估算（Monthly Commute Estimate）**：
將一週預測取樣得到的每週通勤時間乘以四，用來表示一個月四週的估算值。它不是日曆月的精確工作日統計。
_避免使用_：日曆月實際通勤時間、歷史月平均

**固定出發時間模式（Fixed Departure Mode）**：
以使用者明確提供的離家或下班出發時間建立預測通勤樣本，是第一版可完整執行的模式。
_避免使用_：上班時間模式、抵達時間模式

**目標抵達時間模式（Target Arrival Mode）**：
以期望抵達公司的時間為目標，反推建議離家時間。第一版保留此操作入口，但在反推流程完成前必須明確標示為尚未支援。
_避免使用_：固定出發時間模式

**請求預覽（Request Preview）**：
在呼叫 Routes API 前，列出交通模式、目的地數量、取樣日期、正常請求數、重試上限與本機節流設定。正常請求不超過預設門檻二十筆時可以在顯示預覽後執行；超過門檻必須取得使用者明確確認。門檻可由參數調整，但不得關閉預覽。
_避免使用_：API 使用紀錄、執行結果

**執行計畫（Execution Plan）**：
由 `commute-analyzer plan` 在不呼叫外部 API 的情況下，完成設定驗證、日期展開、路線請求建立與 Request Preview 後產生的不可變 JSON。計畫具有依完整有效內容計算的 `plan_id`；任何輸入或設定改變都必須重新產生計畫。
_避免使用_：執行結果、可變暫存、API request log

**計畫執行（Plan Run）**：
由 `commute-analyzer run` 執行既有 Execution Plan。正常請求數不超過成本門檻時，Agent 顯示預覽後可以接續執行；超過門檻時，必須先取得使用者對同一 `plan_id` 的明確確認。
_避免使用_：隱含確認、重新產生計畫、直接呼叫 API

**必要樣本集合（Required Sample Set）**：
一家公司參與正式排名所需的全部機車樣本，包含每個選定日期的住家到公司早上路線，以及公司到住家晚上路線。任何必要樣本在有限重試後仍失敗時，該公司標示為資料不完整並排除排名，但保留成功樣本與錯誤資訊。
_避免使用_：最低成功樣本、部分平均、靜默排除失敗

**主動請求節流（Proactive Request Throttling）**：
在送出 Compute Routes 請求前，由本機排程器依設定的每分鐘請求上限控制速率。預設為 `60 QPM`、一次只送出一筆，允許在 `1–3000` 之間調整；Request Preview 必須說明這是本機設定值，不是已向 Google Cloud 驗證的實際 quota。HTTP `429` 只作為配額或競爭流量超出預期後的復原情境，不得作為正常的流量控制機制。
_避免使用_：遇到 429 才降速、無上限平行請求、保證永不發生 429

**路線查詢結果（Route Query Result）**：
路線查詢 Skill 對單次預測結果提供的穩定結構化資料。預設 `summary` profile 只包含 request ID、狀態、距離、含交通時間、靜態時間、警告、fallback 與地址對應的 Place ID；不包含 polyline、導航步驟、viewport、route token 或完整 Google response。平均通勤 Skill 只依賴此契約，不直接依賴 Google 的原始回應格式。未來有實際用途時可新增具名 output profile，不改變既有 `summary` 契約。
_避免使用_：Google 原始 response、通勤摘要

**嚴格 JSON Envelope（Strict JSON Envelope）**：
跨 Skill CLI 的輸入與輸出都帶有 `schema_version`。必要欄位缺失、型別錯誤或未知欄位都採 fail-closed，錯誤必須指出精確 JSON path；新增欄位須透過新的 schema 版本表達。`stdout` 只包含 JSON，進度與診斷寫入 `stderr`。
_避免使用_：忽略未知欄位、混合文字輸出、無版本 JSON

**降級路線結果（Degraded Route Result）**：
Google 回傳 `fallbackInfo`，表示未完全按照要求的條件計算路線。結果與原因必須保留，但不得算入必要樣本或正式排名。
_避免使用_：成功樣本、完全失敗、忽略 fallback

**地址標籤（Location Label）**：
用於預覽、結果與一般 log 的非敏感名稱，例如 `home` 或公司名稱。預設不得重複輸出完整地址；只有使用者明確指定 `--include-locations` 時，結果才可包含位置內容。
_避免使用_：完整地址、Place ID、座標

**API 使用帳本（API Usage Ledger）**：
存放於私人資料目錄的 append-only JSONL，只記錄執行時間、預計與實際請求數、成功、失敗、重試數、交通模式及推定 SKU 類別。不得記錄地址、API key、路線時間或 Google 原始 response。私人資料目錄在 Windows 為 `%LOCALAPPDATA%\command1264-skills\commute-analyzer`，macOS 為 `~/Library/Application Support/command1264-skills/commute-analyzer`，Linux 為 `${XDG_DATA_HOME:-~/.local/share}/command1264-skills/commute-analyzer`。
_避免使用_：路線快取、通勤歷史、原始 response log

**通勤報告（Commute Report）**：
由相同分析結果產生的版本化 JSON 與繁體中文 Markdown。預設寫入私人資料目錄的 `reports` 子目錄，檔名只包含執行日期與不含地址的 report ID；`--output-dir` 可明確覆寫位置。機車必要樣本完整的公司可參與機車排名；只有汽車樣本不完整時，不影響機車排名，但汽車欄位必須標示不完整。
_避免使用_：repository 報告、歷史實測、完整地址檔名

**私人通勤設定（Private Commute Configuration）**：
存放於作業系統標準使用者設定目錄的通勤設定檔。Windows 使用 `%APPDATA%\command1264-skills\commute-analyzer\config.json`，macOS 使用 `~/Library/Application Support/command1264-skills/commute-analyzer/config.json`，Linux 使用 `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/commute-analyzer/config.json`；`COMMUTE_ANALYZER_CONFIG` 可明確覆寫位置。此檔不得包含 API key；Google credential 由 `google-routes` v2 自己的使用者層級 TOML secret file 擁有、解析與使用。公開 repository、輸出與一般 log 均不得包含私人地址或 secret。
_避免使用_：repository 設定、公開範例設定

**公司設定（Company Configuration）**：
私人通勤設定中的可重用目的地，包含穩定 `id`、顯示名稱，以及恰好一種 `address` 或 `place_id`。CLI 也可加入只用於當次計畫的公司，不自動寫回私人設定；未來的公司別早晚時間覆寫不是第一版行為。
_避免使用_：公開公司清單、自動保存臨時輸入、多個位置來源

**Place ID 建議更新（Suggested Place ID Update）**：
地址查詢成功後，結果可以提供 Google 回傳的 Place ID 並建議使用者更新私人設定，但程式不得自動改寫設定。設定更新必須是明確、獨立的使用者操作。
_避免使用_：自動遷移、靜默改寫、路線快取

**明確 UTC Offset（Explicit UTC Offset）**：
通勤設定用於建立未來出發時間的固定時區偏移，例如 `+08:00`。第一版使用 Python 3.11 以上與標準函式庫，不依賴外部時區資料；因此不宣稱支援會隨日期切換的日光節約時間規則。
_避免使用_：IANA 時區、完整 DST 支援、本機隱含時區

**部分成功（Partial Success）**：
批次分析中至少一個目的地成功且至少一個目的地失敗的結果狀態。成功項目必須保留，失敗項目必須附帶可操作的結構化錯誤。
_避免使用_：成功、整批失敗、忽略錯誤

**通勤排序（Commute Ranking）**：
多公司比較時，依機車每日來回平均時間由短至長排列的結果。第一版不使用不透明的綜合分數。
_避免使用_：通勤評分、職缺排名
