# 安全與隱私規則

處理 secret、私人位置、外部 API、log、cache、ledger、報告或安全回報時適用。

## Secret 與私人資料

- 持久 API key 必須由 provider Skill 擁有的使用者層級、版本化 secret store 取得，不得
  透過環境變數 fallback、hardcode、commit、回傳、寫入一般 log 或附在 Issue／PR。
- Secret store 不得放在 repository、Skill 安裝目錄或同步資料夾；consumer Skill 不得
  重新解析或傳遞 provider 的明文 credential。
- 完整住家地址、私人設定、未去識別 response 與產生的個人報告不得進入公開 repository。
- 預設輸出使用非敏感 label；只有使用者明確要求時才顯示完整位置，而且仍不得顯示 secret。
- 測試與文件使用虛構位置、官方公開範例或不可逆的去識別資料。

## 跨 runtime 私人儲存

- 選定 config、credential、cache、ledger 或其他持久資料路徑前，必須從建立檔案的程序與
  實際消費它的代表性 runtime 分別驗證讀寫可見性；相同環境變數字串不代表相同實體檔案。
- Windows 上若資料需要由 packaged 與 unpackaged runtime 共用，預設使用
  `%USERPROFILE%\.config` 保存設定、`%USERPROFILE%\.local\share` 保存資料，避免使用可能受
  MSIX AppData virtualization 影響的 `%APPDATA%`／`%LOCALAPPDATA%`。只有具備代表性
  cross-runtime 證據時才能採用其他路徑。
- 路徑契約改變時，須提供不讀取私人內容的 path／check 診斷與可操作的人工遷移說明；不得
  自動複製、搬移或刪除 secret、私人設定與私人產物。
- 新增或修改 Windows 私人儲存行為時，驗收必須包含 packaged runtime 與一般 runtime；
  只在 PowerShell、測試替身或單一 Python 安裝成功，不足以證明跨 runtime 可用。

## 外部 API

- 呼叫前驗證所有輸入、目標 endpoint、預估請求數、成本門檻與 rate limit；不得以收到
  `429` 作為正常節流方式。
- provider policy、價格、quota、支援地區或 API 契約屬易變資訊，實作與 release review
  必須重新查閱官方一手文件。
- 只要求完成用途所需的最小 field mask。provider raw response 留在 adapter implementation，
  除非明確診斷流程需要，否則不持久化。
- 快取與保存必須逐欄位符合 provider policy；不得因技術上可寫入磁碟就推定允許保存。

## Log、ledger 與報告

- stdout 若承諾 JSON，就不得混入進度或診斷文字；stderr 也必須遮蔽 secret 與位置。
- Usage ledger 只記錄稽核所需的非內容 metadata，不得演變為路線、地址或 response cache。
- 產物預設寫入作業系統私人 data directory，不寫入 repository；檔名不得包含地址。

## 公開回報

安全問題使用 `SECURITY.md` 指定的私密管道。發現公開 Issue 含 secret 或私人位置時，
不要在回覆中重貼內容；先限制擴散並通知維護者依 GitHub 能力移除或編輯。
