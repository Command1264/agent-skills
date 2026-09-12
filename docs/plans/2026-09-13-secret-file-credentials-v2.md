# Secret file credential v2 遷移計畫

## 目標

把 Google Maps Platform API key 從程序環境變數一次遷移到使用者層級的 TOML secret file，讓 credential 不會隨 shell 或 Skill 更新消失，也不會因放在公開 repository 或 Skill 安裝目錄而容易誤提交。

本計畫只改變 API key 的保存、解析與使用邊界。`COMMUTE_ANALYZER_CONFIG` 等非 secret 設定、Skill discovery 使用的環境變數與通勤分析產品功能不在此次移除範圍。

## 追蹤項目

- [`google-routes v2` Issue #10](https://github.com/Command1264/agent-skills/issues/10)：實作 secret file credential 契約並發布 `google-routes-v2.0.0`。
- [`commute-analyzer v1` Issue #3](https://github.com/Command1264/agent-skills/issues/3)：首次發布前改為只接受 `google-routes` major 2。
- [ADR 0007](../adr/0007-use-provider-owned-toml-secret-files.md)：記錄格式、路徑、所有權及一次切換的架構決策。

Issue #3 已在 2026-09-13 更新 credential 驗收條件；其他既有通勤分析範圍不變。`google-routes v2` milestone 留待進入實作／發版流程時建立，避免本規劃任務同時改動不必要的 release 狀態。

## 已確認決策

### 一次切換，不保留環境變數 fallback

- `google-routes v1.0.0` 已發布，移除 `GOOGLE_MAPS_API_KEY` 屬於 breaking interface change，因此下一個穩定版是 `google-routes v2.0.0`。
- v2 query 與 smoke runner 只從 secret file 取得 key。
- 非空的 `GOOGLE_MAPS_API_KEY` 存在時，以穩定錯誤碼拒絕 query 與 smoke 並提供遷移指引；不得靜默忽略後繼續，也不得回退讀取。`credentials path` 與 `credentials set` 必須仍可使用，否則使用者無法完成遷移；`credentials check` 同時驗證檔案並回報舊變數仍需移除。
- `commute-analyzer` 尚未正式發布，所以 v1 可直接要求 `google-routes` Skill major 2 與 CLI contract major 2，不需要發布相容中繼版。

### 檔案位置

| 平台 | 預設路徑 |
| --- | --- |
| Windows | `%USERPROFILE%\.config\command1264-skills\credentials\google-routes.toml` |
| macOS | `~/Library/Application Support/command1264-skills/credentials/google-routes.toml` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/credentials/google-routes.toml` |

- v2 不提供 credential path 的環境變數或命令列 override，避免 secret 散落到 repository、Skill 目錄或臨時路徑。
- Windows 不使用 AppData；Microsoft Store Python 的 MSIX 重導可能讓相同 AppData 文字路徑指向 runtime 私有副本。已在同一 Windows 主機驗證使用者主目錄檔案可同時由 WindowsApps Python 與 Codex bundled Python 讀取。
- 缺少平台必要的使用者目錄資訊時 fail-closed，錯誤須指出應修復的系統設定，但不得猜測或退回目前工作目錄。
- `credentials path` 可顯示解析後路徑，方便使用者找到檔案；這個命令不讀 key、不呼叫 Google API。

### 檔案格式

```toml
schema_version = "1"
api_key = "<Google Maps Platform API key>"
```

- 使用 TOML，而不是 YAML 或 JSON。Python 3.11 的 `tomllib` 可安全讀取，不需新增 production dependency；兩個欄位仍容易手動閱讀與更新。
- schema v1 只允許上述兩個頂層欄位。缺欄、重複、未知欄位、錯誤型別、空值與明顯 placeholder 均 fail-closed。
- 不用固定前綴或長度判斷 Google key，以免 Google 未來格式改變造成不必要的不相容。
- 讀取前驗證為一般檔案且不超過 8 KiB，避免誤讀裝置、目錄或異常大型檔案。

## Module 與介面邊界

### `google-routes` credential module

新增 provider-owned credential module，集中隱藏以下複雜度：

- 跨平台預設路徑解析。
- 舊環境變數偵測。
- TOML 讀取、schema 驗證與錯誤正規化。
- 互動式安全輸入、目錄建立、權限處理及 atomic replace。
- 所有錯誤與診斷的 secret 遮蔽。

公開 query CLI 不接受 `--api-key`、key stdin 欄位或 credential path。核心 HTTP adapter 仍可接受已解析的 key 作為內部 dependency injection，讓離線測試不需要碰觸真實使用者檔案；這不是公開 credential interface。

### `commute-analyzer` 的責任

- 透過 `capabilities` 驗證 `google-routes` Skill major 2、CLI contract major 2 與既有 route schema／profile 能力。
- 不開啟 secret file、不解析 TOML、不檢查 key 內容，也不把 key 放進 plan、subprocess argument、報告或 ledger。
- 執行 query 時由 `google-routes` 自己解析 credential；credential 錯誤只以穩定、去識別化的 dependency error 傳回。
- 發布 smoke runner 沿用請求硬上限，但移除自己檢查 `GOOGLE_MAPS_API_KEY` 的邏輯。

這個 seam 讓未來改成 OS keychain 或外部 secret manager 時，只需替換 provider Skill 內部 implementation，再透過新的 major 契約發布，不需把 credential 邏輯複製到每個 consumer Skill。

## Credential CLI 契約

所有 credential 管理命令均不呼叫 Google API，stdout 維持 machine-readable JSON，互動提示與診斷走 stderr。

### `credentials path`

- 回傳 schema version 與解析後的預設檔案路徑。
- 不建立目錄或檔案，不讀取 key。

### `credentials check`

- 驗證路徑、檔案型態、大小、TOML schema 與最低權限要求。
- 只回傳 `configured`、`schema_version` 與穩定 warning／error code。
- 不回傳 key、長度、hash、前綴、後綴、原始 TOML 或可用來比對 key 的衍生值。

### `credentials set`

- 只允許互動式 TTY；使用 Python `getpass` 隱藏輸入，不接受命令列 `--api-key`。
- 建立父目錄後，在同一目錄寫入權限受限的暫存檔，flush 後以 `os.replace` 原子替換。
- POSIX 建立檔案時使用 `0600`。Windows 放在目前使用者主目錄的 `.config` 並繼承 user-profile ACL；不宣稱純標準函式庫能完整重寫 Windows ACL。
- 成功訊息只顯示檔案路徑與 schema version。更新失敗時保留既有有效檔案，清除本次建立的精確暫存檔。
- 文件同時提供手動建立 TOML 的方式，讓不方便使用互動式命令的使用者仍可重現設定。
- 即使舊環境變數仍存在也允許執行，因為這是完成遷移所需的管理操作；寫入內容只能來自本次隱藏輸入，絕不從舊變數複製。

## 錯誤模型

建議使用下列穩定 code；實作時可調整名稱，但 CLI contract、文件與測試必須同步：

| code | 條件 | 使用者可採取的動作 |
| --- | --- | --- |
| `legacy_api_key_environment_variable` | 偵測到非空的 `GOOGLE_MAPS_API_KEY` | 移除舊變數並建立 secret file |
| `credential_directory_unavailable` | 無法解析標準使用者目錄 | 修復平台使用者目錄設定 |
| `credential_file_not_found` | 預設檔案不存在 | 執行 `credentials set` 或手動建立 |
| `credential_file_not_regular` | 路徑不是一般檔案 | 移除錯誤物件並建立一般檔案 |
| `credential_file_too_large` | 檔案超過 8 KiB | 只保留 schema 與 key |
| `credential_file_invalid` | TOML 或 schema 不合法 | 依範例修正檔案 |
| `credential_file_permissions_unsafe` | 權限明顯過寬 | 收緊權限後重試 |
| `credential_interactive_required` | `credentials set` 不是在互動式終端執行 | 改由使用者在終端執行 |
| `credential_update_failed` | 安全寫入或替換失敗 | 保留舊檔，依不含 secret 的診斷修復 |

錯誤中只允許標準路徑、欄位名稱與修復指引，不得包含 key、原始檔案內容、私有地址或 provider response。

## 實作階段

### 階段 1：`google-routes v2` 離線實作

1. 先以 RED 測試固定預設路徑、嚴格 TOML schema、舊環境變數拒絕、不洩密與 atomic update。
2. 新增 credential module 與三個管理命令，再把 query CLI 與 google-routes smoke runner 接到同一 resolver。
3. 提升 Skill SemVer、CLI contract 與 capabilities major；route result schema 未變時保持原版本。
4. 更新 `skills/google-routes/SKILL.md`、references、CHANGELOG、README、`CONTEXT.md`、安全規則及 repository foundation 中已過時的環境變數敘述。
5. 執行 unit、CLI integration、repository validator、secret scan 與三平台 CI；CI 全程使用臨時測試目錄與假 key，不讀真實使用者檔案。

停止條件：若 Windows 權限驗收只能靠額外 production dependency、需寫 registry，或無法保證更新失敗時保留舊檔，先停止 credential writer；resolver 與手動設定文件可獨立評估，但不得降低不洩密門檻。

### 階段 2：`commute-analyzer v1` 採用 v2

1. 先以 RED 測試固定 major 1 dependency 被拒絕、major 2 可用、credential error 正確轉譯且沒有 key 洩漏。
2. 更新 capabilities 驗證、執行流程與 smoke runner，刪除 commute 端所有 API-key 環境變數檢查。
3. 更新 SKILL、CLI contract、private-data／smoke references、CHANGELOG 與 Issue #3 對應驗收證據。
4. 執行既有完整 mock integration suite，確認 plan hash、請求數、節流、報告與 ledger 行為未因 credential 遷移改變。

停止條件：如果 consumer 必須讀取或傳遞明文 key 才能工作，表示 provider CLI seam 不夠深，先回到 `google-routes` 修正介面，不在 commute 端複製 credential resolver。

### 階段 3：真實 smoke 與發布

1. 使用者建立一把受 Routes API 限制、可撤銷的新 key，透過互動式命令或手動 TOML 寫入預設位置。
2. 先執行 `credentials check`；確認 process、User、Machine scope 都沒有非空的 `GOOGLE_MAPS_API_KEY`。
3. 產生新的 smoke plan／plan hash，取得當次明確核准後，最多執行一筆 `TWO_WHEELER` 與一筆 `DRIVE`；不沿用舊 plan 或舊 key。
4. smoke 證據只記錄去識別化結果、request count、HTTP 結果類別與節流資料，不保存 key、地址或完整 Routes response。
5. 依 `develop` → release PR → `main` 流程發布 `google-routes-v2.0.0`，再完成 `commute-analyzer v1` 的 release gate。

停止條件：credential check 未通過、API key 未限制、quota／billing 狀態不明、plan hash 改變、可能超過兩筆 request，或任何輸出含 secret／私人位置時，不送出真實 request，也不進入發布。

## 影響檔案清單

實作前應至少重新搜尋 `GOOGLE_MAPS_API_KEY`，並逐一處理：

- `skills/google-routes/` 的 SKILL、CLI、smoke runner、references、tests 與 CHANGELOG。
- `skills/commute-analyzer/` 的 SKILL、runner、smoke runner、references、tests 與 CHANGELOG。
- repository `README.md`、`CONTEXT.md`、`docs/agents/security-and-privacy.md`、既有 foundation plan 中的歷史／現況敘述。
- `tests/` 中所有以環境變數注入 key 的 unit 與 integration test。

歷史計畫若保留當時決策，應加上「已由 ADR 0007／Issue #10 取代」註記，而不是重寫成彷彿當時就採 secret file；現行操作指南則必須完全移除舊做法。

## 驗收證據

- 所有受影響 Python 測試與 repository validator 通過。
- `rg "GOOGLE_MAPS_API_KEY"` 只剩明確的 migration rejection、歷史註記與對應測試；不得剩下設定或 fallback 指引。
- 以臨時 HOME／AppData 執行的 CLI 測試證明不接觸開發者真實 credential。
- 對 stdout、stderr、exception 與產物做 canary secret 掃描，結果為零洩漏。
- `credentials set` 的失敗注入測試證明既有有效檔案未被破壞。
- `commute-analyzer` 使用 major 2 mock dependency 完成 end-to-end，使用 major 1 或 credential error 時在 API request 前 fail-closed。
- 真實 smoke 屬後續獨立驗收，沒有實際 request 證據前不得宣稱 Routes API credential 已在真實環境可用。

## 不在本次範圍

- OS keychain、Windows Credential Manager、macOS Keychain、Secret Service 或雲端 secret manager。
- 多個 Google project／profile、自動 rotation、key 建立或 Google Cloud Console 自動化。
- 把 secret file 放在 `.agents/skills`、`.codex/skills`、repository、Skill script 隔壁或同步資料夾。
- 移除與 API key 無關的環境變數。
- 本規劃任務不修改 Skill runtime、不呼叫 Google API、不 push、不建立 PR、不 merge、不 tag、不發布。

## 後續核准邊界

本文件與 GitHub Issue 只完成可執行規劃，不代表已核准實作、真實 API request、push、PR、merge、tag 或 release。下一階段應先核准 Issue #10 的離線實作；完成 Agent 驗證後交付使用者驗收，再依當時明確授權處理 remote 操作。
