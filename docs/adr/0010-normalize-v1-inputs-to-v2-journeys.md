# 將 v1 輸入正規化為 v2 Journey 並拒絕 v1 Plan

`commute-analyzer v2` 繼續接受成對的 v1 config 與 v1 plan request，但先透過 Compatibility Adapter
正規化成唯一的 v2 Journey planning model；原生 v2 只接受成對 v2 inputs，跨版本組合拒絕。所有新
Execution Plans 與 Results 一律是 v2，`run` 對既有 plan v1 在任何 dependency、credential、API 或
輸出操作前要求重新離線產生。這避免強迫使用者立即改寫私人 config，也避免平行維護兩套會影響
request count、確認門檻與分析結果的 runner；代價是升級後不能直接執行尚未過期的舊 plan。沒有選擇
自動改寫或搬移 config，因私人資料遷移必須由使用者明確執行；也沒有保留完整 v1 execution path，
因短期 plan 可安全重建，而雙軌執行會長期放大成本與驗證風險。
