# 測試與 CI 規則

修改 Python、JSON schema、tests、repository validator 或 GitHub Actions 時適用。

## 一般驗證

- 行為變更優先使用 RED → GREEN → REFACTOR；文件或純結構變更採相稱的靜態檢查。
- Python 最低版本為 3.11。第一版執行與測試工具只使用標準函式庫，新增 production
  dependency 必須另行決策與核准。
- 從 module 的公開 interface 驗證可觀察結果，不讓測試依賴私有函式或 provider
  response 的未承諾欄位。
- JSON examples 與 schemas 必須互相驗證；未知欄位、缺少欄位、型別錯誤及版本不相容
  都應有回歸測試。

## 外部服務

- 第三方 API 使用注入的 adapter；CI 使用 mock adapter，不持有真實 secret，也不呼叫
  billable endpoint。
- 真實 API smoke test 必須明確 opt-in、具有程式硬上限，並在執行前顯示請求數。
- smoke test 證據只保留通過／失敗、時間、版本與去識別統計，不保存地址、Place ID、
  API key 或 provider 原始 response。

## CI 支援面

- Foundation CI 在 Windows、Ubuntu、macOS 與 Python 3.11 執行 repository validator、
  unit tests 與 compile check。
- 平台特有程式碼必須在對應 runner 測試；未實際執行的平台只能標示未驗證。
- CI failure 必須提供可操作訊息與失敗檔案，不使用空 catch 或吞掉 subprocess exit code。

## 本機命令

```powershell
python scripts/validate_repository.py
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
```
