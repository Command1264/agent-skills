# Agent Skills repository foundation 計畫

## 目標

建立公開的 `Command1264/agent-skills` repository foundation，讓未來 Skills 能以 `npx skills add` 容易安裝、在支援平台重現驗證，並以繁體中文作為權威文件語言。本階段不實作 `google-routes` 或 `commute-analyzer`。

## 已確認的產品邊界

- Repository 採 MIT License，GitHub default branch 為穩定 `main`，日常整合分支為 `develop`。
- Skills 位於 `skills/<skill-name>/`，各自具有獨立 SemVer、`CHANGELOG.md` 與 release tag。
- `google-routes` 是 Google Routes 專屬的基礎 Skill；`commute-analyzer` 透過穩定 JSON CLI 契約組合它。
- 兩個 Skill 可獨立安裝；`commute-analyzer` 找不到或不相容的 `google-routes` 時拒絕執行並提供標準安裝指引。
- 私人地址、API key、設定與報告不進入公開 repository、一般 log 或 Issue。
- GitHub Issues 是唯一工作追蹤系統；第一版不建立 GitHub Project board。

## 交付順序

```text
Repository foundation
        |
        v
google-routes v1
        |
        v
commute-analyzer v1
```

`commute-analyzer` 不得與 `google-routes` 平行進入正式實作，直到後者的 CLI contract、schema v1 與 capabilities 已通過驗收並形成可引用的版本。

## 第一階段範圍：Repository foundation

### Repository 與文件

- 初始化本機 Git，以 `main` 建立最小穩定基線，再建立 `develop`。
- 建立公開 GitHub repository `Command1264/agent-skills`，保留 `main` 為 default branch。
- 新增 `README.md`、`LICENSE`、`CONTRIBUTING.md`、`SECURITY.md` 與 `.gitignore`。
- `README.md` 說明 repository 定位、繁中權威語言、穩定版與開發版差異，以及一般 `npx skills add` 使用方式；在 Skill 尚未發布前不得放入假裝可用的安裝命令。
- `SECURITY.md` 將安全問題導向 GitHub Private Vulnerability Reporting；公開表單警告不得貼出 API key、完整住家地址、私人設定或未去識別的 response。

### Agent 指引

根目錄 `AGENTS.md` 維持小型 router，每個指標同時寫出觸發條件與目標文件：

- 建立或修改 Skill 時讀 `docs/agents/skill-authoring.md`。
- 修改 Python、schema、測試或 CI 時讀 `docs/agents/testing.md`。
- 處理 secret、私人位置、外部 API、log 或報告時讀 `docs/agents/security-and-privacy.md`。
- 版本、tag、發布、穩定分支或安裝文件變更時讀 `docs/agents/release.md`。

第一版不在每個 Skill 內複製 `AGENTS.md`；只有真正出現不同規則時才加入較近的 router。

### GitHub Issues

建立繁體中文 Issue Forms：

1. 新 Skill 提案。
2. 既有 Skill 功能改進。
3. Bug 回報。
4. 文件／維護工作。

關閉 blank issues。保留既定 triage labels：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`；另加入可擴充的 `type:*` 與 `area:*` labels，而不是為每個未來 Skill 建立硬編碼流程。

建立 milestones：`Repository foundation`、`google-routes v1`、`commute-analyzer v1`。

### CI 與驗證

- GitHub Actions 以 Python 3.11 在 Windows、Ubuntu、macOS 執行。
- 驗證 Skill discovery、`SKILL.md` 基本結構、內部 Markdown links、JSON examples／schemas、Python unit tests 與 mock integration tests。
- CI 不持有 `GOOGLE_MAPS_API_KEY`，也不呼叫 Google API。（歷史決策；credential 來源已由 ADR 0007 取代。）
- 真實 API smoke test 只允許本機明確 opt-in，受兩筆請求硬上限保護，並輸出去識別化證據。
- Agent 規則鏈從 repository root 與 `skills/<name>/` 代表路徑做靜態 walkthrough；沒有 runtime 證據時不得宣稱模型已實際載入。

## 三個 GitHub Issue 草案

### Issue 1：`chore: 建立公開 Agent Skill repository foundation`

**目的**：完成不含正式 Skill implementation 的 repository、文件、Agent router、Issue Forms、labels、milestones 與離線 CI。

**驗收**：

- [ ] `main` 是 GitHub default branch，`develop` 可供日常整合。
- [ ] MIT、README、CONTRIBUTING、SECURITY 與隱私警告可由公開首頁找到。
- [ ] 四份 Agent 指引只有單一權威來源，root router 低於 24 KiB 且所有連結有效。
- [ ] 四種 Issue Forms 可建立正確 labels，blank issues 已關閉。
- [ ] 三個 milestones 與 triage labels 已建立並核對。
- [ ] Windows、Ubuntu、macOS 的 foundation CI 通過。
- [ ] Repository 與 CI 不含 secret、私人地址或真實 Routes response。

### Issue 2：`feat(google-routes): 建立 Google Routes 查詢 Skill v1`

**目的**：提供可獨立安裝、以 Python 3.11 標準函式庫執行的 Routes API Skill，接受帶版本的批次 JSON 並回傳穩定結果。

**驗收**：

- [ ] `npx skills add Command1264/agent-skills --skill google-routes` 可發現並安裝 Skill。
- [ ] `capabilities` 不呼叫 API，正確回報版本、schema、模式與 profiles。
- [ ] Batch CLI 以 `request_id` 對應逐筆成功、降級或失敗；stdout 只有 JSON，stderr 只有診斷。
- [ ] `TWO_WHEELER` 使用 `TRAFFIC_AWARE`；`DRIVE` 使用 `TRAFFIC_AWARE_OPTIMAL` 與 `BEST_GUESS`。
- [ ] `summary` 只回傳距離、含交通時間、靜態時間、warnings、fallback 與 Place ID，不輸出完整 response。
- [ ] 預設 60 QPM 主動節流；網路、429、5xx 有界重試兩次並遵守 `Retry-After`。
- [ ] 不持久快取 Routes content；mock tests 涵蓋成功、429、5xx、4xx、fallback、警告與部分成功。
- [ ] 條件式本機 smoke test 通過，證據已去識別化。

### Issue 3：`feat(commute-analyzer): 建立一週預測通勤分析 Skill v1`

**目的**：組合 `google-routes`，針對住家與單一或多家公司建立一週未來交通預測，輸出 JSON 與繁體中文 Markdown。

**驗收**：

- [ ] Skill 可獨立安裝；缺少或不相容的 `google-routes` 時 fail-closed 並顯示安裝／更新方式。
- [ ] 相依解析依序支援環境變數、兄弟目錄、專案 scope 與使用者 scope，並揭露實際路徑。
- [ ] 私人設定跨 Windows、macOS、Linux 使用標準位置，API key 僅取自 `GOOGLE_MAPS_API_KEY`。（歷史決策；已由 ADR 0007 取代。）
- [ ] `plan` 不呼叫 API，產生不可變 `plan_id`、日期、請求數、重試上限、SKU 推定及節流預覽。
- [ ] `run` 只執行既有 plan；超過二十筆時必須確認同一 `plan_id`。
- [ ] 預設下一個星期一開始、一週、週一至週五，早上住家到公司、晚上公司到住家。
- [ ] 完整機車樣本才參與排名；汽車資料不完整不影響機車排名。
- [ ] JSON 保留精確秒數；繁中 Markdown 顯示平均、中位數、最短、最長、每日來回、每週與四週月估算。
- [ ] 報告與 API usage ledger 只寫入私人 data directory，不含完整地址、secret 或 Routes content cache。
- [ ] mock integration tests 涵蓋完整成功、公司部分失敗、fallback、相依缺失、版本不相容與 plan 失效。

## 第一階段停止條件

- `Command1264/agent-skills` 名稱不可用或 GitHub owner 不正確時，停止 remote 建立並請使用者選擇名稱。
- GitHub Private Vulnerability Reporting 無法啟用時，先保留 `SECURITY.md` 的替代私密聯絡方式草案，不公開虛構管道。
- `npx skills` 對預定目錄的 discovery 行為與官方文件不一致時，先建立最小本機 probe，未通過前不宣稱可安裝。
- Foundation CI 或 Agent 規則鏈未通過時，不開始 `google-routes` 正式實作。

## 執行授權與 remote 邊界

本文件是規劃產物，不授權建立 GitHub repository、push、建立 Issues、labels、milestones、啟用安全功能或合併分支。開始第一階段前須由使用者針對上述 foundation 範圍明確核准；任何 Skill implementation 另屬後續 Issue 範圍。

## 參考來源

- [Agent Skills CLI README](https://github.com/vercel-labs/skills/blob/main/README.md)
- [Agent Skills lockfile implementation](https://github.com/vercel-labs/skills/blob/main/src/skill-lock.ts)
- [Routes API usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
- [Compute Routes reference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes)
- [Google Maps Platform policies](https://developers.google.com/maps/documentation/routes/policies)
