# 由 provider Skill 擁有 TOML secret file

`google-routes` 使用使用者層級的 TOML secret file 保存與解析 Google Maps Platform API key，不再讀取 `GOOGLE_MAPS_API_KEY`。Windows 預設為 `%USERPROFILE%\.config\command1264-skills\credentials\google-routes.toml`，macOS 預設為 `~/Library/Application Support/command1264-skills/credentials/google-routes.toml`，Linux 預設為 `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/credentials/google-routes.toml`。Windows 不使用 AppData，因為 Microsoft Store Python 的 MSIX 檔案重導會使相同 AppData 路徑在 packaged 與一般 runtime 下指向不同實體檔案。檔案格式為帶 `schema_version` 的嚴格 TOML；v2 不提供環境變數或命令列路徑 override。

Credential 解析、驗證、更新與遮蔽由 `google-routes` 單一 module 負責，`commute-analyzer` 只驗證 dependency major 2 並呼叫其公開 CLI，不讀取或傳遞明文 key。互動式設定命令以隱藏輸入和 atomic replace 寫檔；查詢、檢查、錯誤與測試證據不得洩露 key 或其可辨識片段。偵測到非空的舊環境變數時 fail-closed 並提示遷移，避免看似切換但仍由舊 credential 控制。

選擇 TOML 是因為 Python 3.11 可用標準函式庫 `tomllib` 讀取，兼顧可讀性與零 production dependency；不選 YAML 是因為標準函式庫沒有安全 parser，不應為兩個欄位引入額外依賴。固定使用者層級路徑可避免 secret 隨 Skill 更新消失或誤入 Git，但不等同 OS keychain：檔案備份、撤銷與 key rotation 仍由使用者管理。這項變更中斷已發布的 v1 credential 契約，因此以 `google-routes v2.0.0` 發布；尚未發布的 `commute-analyzer v1` 直接依賴 v2，不保留環境變數相容層。
