# 使用零相依 Python 與明確 UTC offset

兩個 Skill 的可執行邏輯使用 Python 3.11 以上及標準函式庫，不在 `npx skills add` 之外增加套件安裝程序。`commute-analyzer` 第一版以明確 UTC offset 建立帶時區的未來出發時間，不依賴 IANA 時區資料；私人設定依作業系統慣例儲存，並允許 `COMMUTE_ANALYZER_CONFIG` 覆寫。這能降低公開 Skill 的安裝摩擦並提高離線可重現性，代價是第一版不支援會隨日期改變的日光節約時間規則；需要 DST 的使用者必須等待後續加入可選時區資料方案，而不能把固定 offset 當成完整時區。
