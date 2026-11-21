# 以整庫版本發布 Skill 庫

`npx skills` 固定安裝時記錄 Git ref；只改 GitHub Release 標題，安裝紀錄仍會顯示帶 Skill 名稱的 tag。自 `v1.0.0` 起，同一次整庫發布使用無前綴且相同的 Git tag 與 Release 標題，讓安裝版本有單一序列，也避免各 Skill 使用相同版本號時發生 tag 衝突。各 Skill 的相容性仍由獨立版本與 changelog 表達，既有 tag 和對應 Release 原樣保留，已固定版本的安裝不需要遷移。

本決策取代 [ADR 0006](0006-version-and-verify-skills-independently.md) 的 tag 命名，保留其 Skill 版本與執行期相依驗證；操作規則見[版本與發布規則](../agents/release.md)。
