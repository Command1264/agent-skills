# Command1264 Agent Skills

這是一個以繁體中文維護的公開 Agent Skill 庫，目標是讓每個 Skill 都容易安裝、
可重現驗證，並清楚揭露外部服務、成本、隱私與相依性限制。

## 目前狀態

Repository foundation、`google-routes` v2 與 `commute-analyzer` v1 穩定版已發布。

規劃中的第一批 Skills：

| Skill | 用途 | 狀態 |
| --- | --- | --- |
| `google-routes` | 封裝 Google Routes API，輸出穩定 JSON | v2.1.0 |
| `commute-analyzer` | 以未來工作日樣本估算並比較住家與公司的通勤時間 | v1.1.0 |

## 安裝

在 PowerShell 切換到使用者主目錄，再用一條指令安裝這個 repository 目前提供的所有 Skills：

```powershell
Set-Location $HOME
npx skills add Command1264/agent-skills
```

[`npx skills add`](https://github.com/vercel-labs/skills) 會將 Skills 安裝到執行目錄下的
`.agents/skills`；因此上述流程的安裝位置是 `~/.agents/skills`。若改在某個專案目錄執行，則只有
該專案會使用 `<專案>/.agents/skills`。重新啟動 Agent 或開啟新工作階段後，即可讓 Agent 發現
新安裝的 Skills。

這條命令會一併安裝 `google-routes` 與 `commute-analyzer`；日後 repository 新增 Skills 時，
再次執行同一條命令也會一併安裝。`commute-analyzer` 執行時需要相容的 `google-routes` v2；缺少或版本
不相容時會停止，不會靜默安裝、降級或複製相依實作。

安裝本身不會呼叫 Google API。只有執行路線 `query` 或已確認的 commute `run` 才可能產生
真實 API request 與費用；`capabilities`、credential／config 檢查及 commute `plan` 都是離線操作。

## 安裝後設定

### 1. 設定 Google Routes API key

先在 Google Cloud project 啟用 billing 與 Routes API，建立只允許 Routes API、並依使用情境限制
來源的 API key。不要把 key 貼進對話、命令列、repository、一般 config 或 Skill 目錄。

在互動式 PowerShell 執行以下命令：

```powershell
python "$HOME\.agents\skills\google-routes\scripts\google_routes.py" credentials path
python "$HOME\.agents\skills\google-routes\scripts\google_routes.py" credentials set
python "$HOME\.agents\skills\google-routes\scripts\google_routes.py" credentials check
```

`credentials set` 會以隱藏輸入讀取 key，並保存到使用者層級的 TOML secret file；Windows 預設是
`%USERPROFILE%\.config\command1264-skills\credentials\google-routes.toml`。更新 key 時重新執行
`credentials set` 即可。完整限制、macOS／Linux 路徑及 Windows ACL 檢查見
[`google-routes` credential 說明](skills/google-routes/references/credentials.md)。

### 2. 建立 commute 私人設定

先查看程式實際選用的設定路徑：

```powershell
python "$HOME\.agents\skills\commute-analyzer\scripts\commute_analyzer.py" config path
```

Windows 新安裝的預設位置是
`%USERPROFILE%\.config\command1264-skills\commute-analyzer\config.json`。在該位置自行建立 UTF-8
JSON，並只在本機填入真實地址。例如：

```json
{
  "schema_version": "1",
  "home": {
    "label": "住家",
    "location": { "address": "請在本機填入住家地址" }
  },
  "companies": [
    {
      "id": "baseline-company",
      "name": "基準公司",
      "location": { "address": "請在本機填入公司地址" }
    }
  ],
  "utc_offset": "+08:00",
  "morning_departure_time": "08:00",
  "evening_departure_time": "18:00"
}
```

設定檔目前至少需要一家公司。請勿在其中加入 API key，也不要將設定檔 commit、貼到公開 Issue／PR
或放進同步資料夾。建立後執行完全離線的檢查：

```powershell
python "$HOME\.agents\skills\commute-analyzer\scripts\commute_analyzer.py" config check
```

其他平台路徑、私人報告與 Windows 舊路徑遷移方式見
[`commute-analyzer` 私人資料說明](skills/commute-analyzer/references/private-data.md)。

### 3. 臨時評估應徵公司

應徵公司的地址會頻繁改變時，不必每次修改 config。請在本次 plan request 的
`additional_companies` 加入一至多家公司；它們只會附加到這次分析，不會寫回 config：

```json
{
  "schema_version": "1",
  "weeks": 1,
  "weekdays": [1, 2, 3, 4, 5],
  "travel_modes": ["DRIVE"],
  "rate_limit_qpm": 60,
  "additional_companies": [
    {
      "id": "candidate-company",
      "name": "本次應徵公司",
      "location": { "address": "請只在私人 plan 填入公司地址" }
    }
  ]
}
```

將內容保存為不進版控的私人 `plan-request.json`，先產生離線 plan：

```powershell
Get-Content .\plan-request.json | python "$HOME\.agents\skills\commute-analyzer\scripts\commute_analyzer.py" plan > .\private-plan.json
```

此時尚未呼叫 API。檢查 plan 中的 request 數、最多 HTTP request 數、SKU、QPM 與 `plan_id`，
確認 Google Cloud quota 後，才依 Skill 提示決定是否執行 `run`。

目前 plan 的起點仍固定取自 config 的 `home`。若要在住家與租屋處之間切換，可各自保存一份私人
config，並以 `plan --config <路徑>` 選擇；目前不能在 plan request 內臨時覆寫起點。
`commute-analyzer` v1 目前仍不支援中途停靠點；`google-routes` v2.1.0 已能查詢最多 10 個
固定順序停靠點。只需臨時查詢任意起點、終點或多站路線，不需要通勤平均時，可直接要求 Agent
使用 `google-routes`。命名地點與多站通勤分析將由 `commute-analyzer` v2 提供。

詳細欄位、確認門檻、輸出與錯誤處理見
[`commute-analyzer` CLI contract](skills/commute-analyzer/references/cli-contract.md)。

## Repository 結構

```text
skills/<skill-name>/       可獨立安裝的 Skills
docs/agents/               Agent 按需指引
docs/adr/                  架構決策紀錄
docs/plans/                經確認的實作計畫
.github/ISSUE_TEMPLATE/    GitHub Issue Forms
scripts/                   Repository 驗證工具
tests/                     不需外部 secret 的測試
```

本專案的標準 domain 用語以 [`CONTEXT.md`](CONTEXT.md) 為準。

## 語言

`README.md`、`CONTRIBUTING.md`、Issue Forms、Agent 指引與 Skill 說明以繁體中文
為權威版本。程式碼、命令、API、schema 欄位與識別符保留必要英文。日後只有在
出現實際英文讀者需求時，才新增非權威英文翻譯。

## 參與方式

提交提案或錯誤前請閱讀 [`CONTRIBUTING.md`](CONTRIBUTING.md)。安全問題與可能
包含 secret 或私人位置的內容，請依 [`SECURITY.md`](SECURITY.md) 使用私密管道，
不要建立公開 Issue。

## License

[MIT](LICENSE)
