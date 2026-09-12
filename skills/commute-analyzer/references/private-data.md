# 私人資料與輸出

## 預設路徑

| 平台 | config | reports 與 ledger 根目錄 |
| --- | --- | --- |
| Windows | `%APPDATA%\command1264-skills\commute-analyzer\config.json` | `%LOCALAPPDATA%\command1264-skills\commute-analyzer\` |
| macOS | `~/Library/Application Support/command1264-skills/commute-analyzer/config.json` | 同一目錄 |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/commute-analyzer/config.json` | `${XDG_DATA_HOME:-~/.local/share}/command1264-skills/commute-analyzer/` |

可用 `COMMUTE_ANALYZER_CONFIG` 指定 config。`--output-dir` 只改變本次 JSON 與 Markdown
報告目錄，不改變 usage ledger 路徑。

## 資料分類

- 私人設定與 plan：含完整位置，不得 commit、貼入 Issue／PR 或公開 log。
- `GOOGLE_MAPS_API_KEY`：只能由環境變數提供，不得寫入 config、plan、報告或 ledger。
- JSON／Markdown 報告：只保存 label、日期、秒數、狀態、統計與去識別錯誤；不保存完整位置。
- `usage.jsonl`：append-only，每行只記錄 plan ID、時間、request／retry 數、模式與 SKU 計數。
- provider raw response：只在程序記憶體中由 `google-routes` 正規化，不由本 Skill 持久化。

plan 與報告均屬私人產物。若要分享，先人工檢查公司名稱與 label 是否仍能識別個人。
