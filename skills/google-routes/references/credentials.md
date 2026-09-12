# Google Routes credential

`google-routes` v2 只從使用者層級 TOML secret file 取得 API key。其他 Skill、query JSON、
plan、報告、ledger、Issue 與一般 log 都不得保存或傳遞明文 key。

## 預設路徑

| 平台 | 路徑 |
| --- | --- |
| Windows | `%USERPROFILE%\.config\command1264-skills\credentials\google-routes.toml` |
| macOS | `~/Library/Application Support/command1264-skills/credentials/google-routes.toml` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/credentials/google-routes.toml` |

Linux 的 `XDG_CONFIG_HOME` 必須是非空絕對路徑；空值或相對路徑會安全回退到 `~/.config`。

Windows 不使用 AppData。Microsoft Store Python 會將 AppData 對每個套件分別重導，造成相同文字路徑
可能不是同一個實體檔案；使用者主目錄的 `.config` 可由 packaged 與一般 Python 共用。背景可參考
[Python on Windows](https://docs.python.org/3.10/using/windows.html) 與
[MSIX containerization](https://learn.microsoft.com/windows/msix/msix-containerization-overview)。

## 建立或更新

從 `google-routes` Skill 根目錄執行：

```powershell
python scripts/google_routes.py credentials path
python scripts/google_routes.py credentials set
python scripts/google_routes.py credentials check
```

`credentials set` 必須在互動式終端輸入 key，輸入不會顯示，也不會進入命令列歷史。它先在同一目錄
寫入權限受限的暫存檔，再原子替換目標；失敗時保留既有有效檔案。POSIX 檔案必須是 `0600`。
Windows 的 `credentials check` 會回傳 `windows_acl_not_verified` warning，提醒使用者以 `icacls`
人工確認沒有未授權帳號的讀取權限；這項 warning 不代表檔案無效。

也可以手動建立 UTF-8 TOML：

```toml
schema_version = "1"
api_key = "<在本機填入受限的 Google Maps Platform API key>"
```

檔案只能包含上述兩個欄位、不得超過 8 KiB，且 `api_key` 不得為空、包含空白或保留 placeholder。
請勿把真實值貼進對話，或把檔案放進 repository、`.agents/skills`、`.codex/skills`、同步資料夾、
Skill script 隔壁或任何可能提交至 Git 的位置。

## 從 v1 遷移

1. 執行 `credentials set` 建立 secret file；即使舊環境變數仍存在，這個管理命令也能使用。
2. 從目前 process、Windows User／Machine scope 或 shell profile 移除 `GOOGLE_MAPS_API_KEY`。
3. 完整重啟會繼承環境的 Agent／終端，再執行 `credentials check`。
4. `check` 通過後才執行 query 或 smoke。

非空舊環境變數存在時，query 與 smoke 會以 `legacy_api_key_environment_variable` 拒絕執行；
它不會讀取、複製或回退使用舊值。

## Key 管理

- 在 Google Cloud Console 將 key 限制為 Routes API，適用時加入來源 IP restriction。
- 懷疑洩漏時先在 Google Cloud 撤銷或 rotation，再更新本機 secret file。
- 刪除 Skill 不會刪除 secret file；不再使用時由使用者自行刪除精確檔案。
