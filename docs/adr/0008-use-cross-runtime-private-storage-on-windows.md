# Windows 私人資料使用跨 runtime 路徑

## 背景

`commute-analyzer` v1.0.0 將 Windows config 放在 `%APPDATA%`，reports 與 usage ledger 放在
`%LOCALAPPDATA%`。實際驗證發現，Microsoft Store／MSIX packaged Python 可能受到 AppData
virtualization 影響：PowerShell 與 Python 顯示相同路徑字串，卻看見不同實體檔案，造成
PowerShell 已建立 config、Python 仍回報 `CONFIG_NOT_FOUND`。

這不是 config schema 或 API key 問題。只在建立檔案的一方檢查存在性，或只比較 `%APPDATA%`
字串，都不能證明消費端 runtime 可以讀取同一檔案。

## 決策

從 `commute-analyzer v1.1.0` 起，Windows 預設路徑為：

- config：`%USERPROFILE%\.config\command1264-skills\commute-analyzer\config.json`
- reports 與 ledger：`%USERPROFILE%\.local\share\command1264-skills\commute-analyzer\`

`COMMUTE_ANALYZER_CONFIG` 仍可明確覆寫 config。解析時依序採用 override、存在的新預設
config、目前 runtime 可見的舊 `%APPDATA%` config，最後回到尚未建立的新預設路徑。
使用舊 config 時輸出遷移警告；程式不得自動複製、搬移或刪除私人檔案。舊 reports 與 ledger
不需遷移，新執行結果直接寫入新 data 根目錄。

新增完全離線的 `config path` 與 `config check`，讓使用者在不揭露地址、不呼叫外部 API 的
情況下確認目前 runtime 的解析結果與 config 有效性。

## 影響

- packaged 與 unpackaged Windows runtime 可透過不受 AppData virtualization 影響的使用者路徑
  共用設定與資料。
- 已存在且目前 runtime 可見的 v1.0.0 config 可暫時繼續使用，降低升級中斷；仍需人工遷移。
- 新 data 位置不會自動彙整舊 usage ledger，因此升級前後的 ledger 可能分開保存。
- 路徑行為的回歸驗證必須涵蓋建立端與實際消費 runtime，不能只驗證環境變數字串。

## 參考

- [Python install manager on Windows](https://docs.python.org/3.16/using/windows.html)
- [Flexible virtualization for MSIX apps](https://learn.microsoft.com/windows/msix/desktop/flexible-virtualization)
- [MSIX containerization overview](https://learn.microsoft.com/windows/msix/msix-containerization-overview)
