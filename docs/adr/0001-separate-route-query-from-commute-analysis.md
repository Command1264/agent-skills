# 分離路線查詢與通勤分析

`google-routes` 只接受明確的起點、終點、交通模式與出發時間，並透過接受 JSON、輸出 JSON 的 Python CLI 回傳穩定結果；`commute-analyzer` 負責產生工作日與早晚排程、呼叫該 CLI 並計算統計。兩者位於 `skills/<skill-name>/`，維持可由標準 `npx skills add` 獨立安裝，不建立專用安裝器，也不在 `commute-analyzer` 內複製路線查詢實作。執行 `commute-analyzer` 前依序從環境變數覆寫、安裝位置的兄弟目錄、專案層級及使用者層級的 `.agents/skills` 尋找 `google-routes`；缺少時採 fail-closed 並提供安裝指引。這項邊界讓 Google 專屬的 API 行為不會滲入通勤 domain，也讓其他情境可以重用路線查詢能力；代價是目前的 `npx skills` 不會自動安裝相依 Skill，使用者可能需要補做一次安裝，且跨 Skill CLI 必須維持相容。
