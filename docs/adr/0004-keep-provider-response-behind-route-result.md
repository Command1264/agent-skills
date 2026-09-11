# 將供應商 response 保留在路線結果 interface 之後

`google-routes` 的外部 interface 是帶有版本的 JSON envelope 與穩定 `Route Query Result`；預設 `summary` profile 只輸出通勤與基本路線判斷需要的距離、含交通時間、靜態時間、警告、fallback 及 Place ID，不把完整 Google response 當成契約。Google HTTP 呼叫與 response 解析屬於 module implementation，正式測試以 mock adapter 取代外部服務並從同一 interface 驗證。未來只有在地圖、導航、路線建議或診斷等具體用途出現時，才新增具名 output profile；既有 profile 保持相容。這提高呼叫者的 leverage 與維護 locality，也避免 Google 欄位變動擴散；代價是新增用途時需要明確設計並正規化額外欄位，而不能立即任意讀取 raw response。
