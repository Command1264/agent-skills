# 安全與隱私規則

處理 secret、私人位置、外部 API、log、cache、ledger、報告或安全回報時適用。

## Secret 與私人資料

- API key 只能由明確環境變數或使用者核准的 secret store 取得，不得 hardcode、commit、
  回傳、寫入一般 log 或附在 Issue／PR。
- 完整住家地址、私人設定、未去識別 response 與產生的個人報告不得進入公開 repository。
- 預設輸出使用非敏感 label；只有使用者明確要求時才顯示完整位置，而且仍不得顯示 secret。
- 測試與文件使用虛構位置、官方公開範例或不可逆的去識別資料。

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
