# 私人資料與輸出

## 預設路徑

| 平台 | config | reports 與 ledger 根目錄 |
| --- | --- | --- |
| Windows | `%USERPROFILE%\.config\command1264-skills\commute-analyzer\config.json` | `%USERPROFILE%\.local\share\command1264-skills\commute-analyzer\` |
| macOS | `~/Library/Application Support/command1264-skills/commute-analyzer/config.json` | 同一目錄 |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/commute-analyzer/config.json` | `${XDG_DATA_HOME:-~/.local/share}/command1264-skills/commute-analyzer/` |

可用 `COMMUTE_ANALYZER_CONFIG` 指定 config。`--output-dir` 只改變本次 JSON 與 Markdown
報告目錄，不改變 usage ledger 路徑。

先執行 `python scripts/commute_analyzer.py config path` 查看目前選用路徑，再執行
`python scripts/commute_analyzer.py config check` 驗證檔案。兩者完全離線；輸出只包含路徑、
來源與驗證 metadata，不回傳地址等私人內容。

### Windows 舊路徑遷移

v1.0.0 使用 `%APPDATA%` 與 `%LOCALAPPDATA%`，但 packaged Python 的 MSIX AppData
virtualization 可能讓 PowerShell 與 Python 看到相同字串、不同實體檔案。v1.1.0 改用
`%USERPROFILE%` 下的跨 runtime 路徑。

若新 config 不存在且目前 runtime 看得到舊 `%APPDATA%` config，程式會暫時使用舊檔並輸出
`legacy_windows_appdata_path` 警告。請人工將 config 移到 `config path` 顯示的
`default_path`，再執行 `config check`；程式不會自動讀取、複製、搬移或刪除私人檔案。
舊 reports 與 ledger 不需搬移，新執行結果會寫入新的 data 根目錄。

## 資料分類

- 私人設定與 plan：含完整位置，不得 commit、貼入 Issue／PR 或公開 log。
- v2 inline location：只存在於本次私人 request／plan；程式不會加入 Named Location Catalog 或改寫 config。
- v1 config：仍可唯讀搭配 request v1 產生 plan v2；`schema_migration` 只提供人工遷移提示。
- Google Maps API key：只由 `google-routes` v2 的使用者層級 TOML secret file 保存與解析；
  不得寫入 commute config、plan、報告、ledger、subprocess argument 或 environment。
- JSON／Markdown 報告：只保存 label、日期、秒數、狀態、統計與去識別錯誤；不保存完整位置。
  Markdown 顯示會轉義自訂 label，避免將內容解讀為外部圖片、連結或額外段落。
- `usage.jsonl`：append-only，每行只記錄 plan ID、時間、request／retry 數、模式與 SKU 計數。
- provider raw response：只在程序記憶體中由 `google-routes` 正規化，不由本 Skill 持久化。

plan 與報告均屬私人產物。若要分享，先人工檢查 Journey 與 Point labels 是否仍能識別個人。
