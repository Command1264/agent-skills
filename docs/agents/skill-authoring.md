# Skill 撰寫規則

建立或修改 `skills/<skill-name>/`、`SKILL.md`、scripts、references、examples 或
Skill changelog 時適用。

## 結構與語言

- 每個可獨立安裝的 Skill 位於 `skills/<skill-name>/`，目錄與 frontmatter `name`
  使用相同 kebab-case。
- `SKILL.md` 是 Agent 執行指引，不是產品介紹；description 應清楚說明何時使用，
  內容應涵蓋必要輸入、操作順序、停止條件、輸出與驗證。
- 權威說明使用繁體中文，程式碼、命令、API、schema、識別符與引用保留原文。
- 只有被 `SKILL.md` 明確路由的細節才放入 `references/`；確定性工作優先放入
  可測試的 `scripts/`，不要要求 Agent 手算或自行拼接複雜 JSON。
- 範例必須使用虛構、去識別或 provider 官方公開資料，不得依賴作者電腦的絕對路徑。

## Interface 與相依性

- Skill 的 interface 包含輸入、輸出、錯誤模式、設定、順序限制與外部成本；變更前
  先確認 `CONTEXT.md` 與適用 ADR。
- 跨 Skill 呼叫使用帶版本的穩定契約，不解析自然語言輸出，也不直接依賴 provider
  的原始 response。
- `npx skills` 不會自動解決 Skill 相依性。需要其他 Skill 時，執行前驗證其
  capabilities；缺少或不相容時 fail-closed，顯示標準安裝或更新方式，不靜默安裝、
  不複製實作作為備援。
- 不為尚未出現的用途公開 raw provider response 或預建 output profile；新增能力時
  保持既有 schema 與呼叫者相容。

## 版本與文件

- 每個已發布 Skill 維護自己的 `CHANGELOG.md` 與 SemVer。
- 行為、interface、相依性、外部成本、安全限制或安裝方式改變時，同步更新 Skill
  文件、examples、tests、`CONTEXT.md` 或 ADR 中真正受影響的部分。
- README 只宣稱已由實際驗證支持的 Agent、平台與安裝方式。
