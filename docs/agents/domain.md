# Domain 文件

本 repository 採用 single-context domain model。

## 探索前應讀取的文件

文件存在時，讀取：

- Repository root 的 `CONTEXT.md`，了解標準 domain 用語。
- `docs/adr/` 中與目前工作範圍相關的 ADR，了解既有架構決策。

這些文件不存在並不代表錯誤。只有在術語或符合條件的架構決策實際定案
時，才建立對應文件。

## 文件結構

```
/
├── CONTEXT.md
└── docs/
    └── adr/
        ├── 0001-example-decision.md
        └── 0002-another-decision.md
```

## Domain 用語

Skill 名稱、文件、測試、Issue 與實作應一致使用 `CONTEXT.md` 定義的
術語。

若需要的概念尚未定義，先判斷它是否確實屬於本專案特有的 domain 概念。
若是，應先透過 domain modeling 釐清意義，再加入 `CONTEXT.md`。

## 架構決策

若目前方案與既有 ADR 衝突，必須明確指出，不得靜默覆寫既有決策。

只有同時符合以下條件時才建立 ADR：

1. 日後改變決定需要付出明顯成本。
2. 未保留背景時，未來維護者可能無法理解這項決定。
3. 決策過程中存在真實且值得記錄的取捨。
