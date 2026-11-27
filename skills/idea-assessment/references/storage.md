# 私人資料與路徑

報告根目錄依下列順序決定，`path` 指令會顯示目前結果與來源（`argument`、`config` 或 `default`），完全離線：

```bash
python <skill>/scripts/idea_assessment.py path
```

1. **本次參數** `--output-dir <路徑>`：只影響這一次。相對路徑以目前工作目錄為準。
2. **設定檔** `output_root`：長期改變預設位置。相對路徑以設定檔所在資料夾為準，所以不會因為從不同目錄
   執行而跑掉。
3. **平台預設**：

| 平台 | 報告根目錄 | 設定檔 |
| --- | --- | --- |
| Windows | `%USERPROFILE%\.local\share\command1264-skills\idea-assessment\` | `%USERPROFILE%\.config\command1264-skills\idea-assessment\config.json` |
| macOS | `~/Library/Application Support/command1264-skills/idea-assessment/` | 同目錄的 `config.json` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/command1264-skills/idea-assessment/` | `${XDG_CONFIG_HOME:-~/.config}/command1264-skills/idea-assessment/config.json` |

環境變數 `IDEA_ASSESSMENT_CONFIG` 可指定另一個設定檔；指向不存在的檔案時指令會停止並說明，而不是悄悄改用預設。

設定檔格式（只接受這兩個欄位）：

```json
{"schema_version": 1, "output_root": "D:/Notes/Ideas"}
```

使用者要求改預設位置時，提供設定檔路徑與上面的格式，由使用者自己建立或修改；`init` 只建立報告資料夾，
不寫設定檔。每個想法一個 `<YYYY-MM-DD>-<slug>` 資料夾，已存在時 `init` 會拒絕，避免覆蓋舊評估；
重新評估同一想法時換日期或 slug，讓新舊報告可以並排比較。
