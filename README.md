# Command1264 Agent Skills

這是一個以繁體中文維護的公開 Agent Skill 庫，目標是讓每個 Skill 都容易安裝、
可重現驗證，並清楚揭露外部服務、成本、隱私與相依性限制。

## 目前狀態

Repository foundation 與第一個穩定 Skill 已發布。

規劃中的第一批 Skills：

| Skill | 用途 | 狀態 |
| --- | --- | --- |
| `google-routes` | 封裝 Google Routes API，輸出穩定 JSON | v2.0.0 開發中；穩定版 v1.0.0 |
| `commute-analyzer` | 以未來工作日樣本估算並比較住家與公司的通勤時間 | v1 開發中，尚未發布 |

## 安裝

使用 [`npx skills add`](https://github.com/vercel-labs/skills) 選擇並安裝 Skill：

```powershell
npx skills add Command1264/agent-skills --skill google-routes
```

`commute-analyzer` 發布後可獨立選擇安裝，但執行時仍需要相容的 `google-routes`；
缺少依賴時會停止並顯示上述安裝命令，不會靜默安裝。

安裝 Skill 不會呼叫 Google API。真實路線查詢另需 Python 3.11 以上、已啟用 billing
與 Routes API 的 Google Cloud project，以及受限 API key。目前 `main` 上的穩定版 v1
仍使用 `GOOGLE_MAPS_API_KEY`；`develop` 中的 v2 改用使用者層級 TOML secret file，且不
支援環境變數 fallback。成本、quota 與安全設定請以 Google Cloud Console 為準。

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
