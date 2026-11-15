# Festo 智慧工廠網站

Flask 網站，包含商品下單、庫存、製程管理、排程比較／CSV 匯出，以及 2D 工廠。實廠模式沿用原同步程式交換 MES 與 Supabase 資料；離線協作模式使用獨立的假資料，不會向工廠送單。

## 直接部署成一個網站

[部署到 Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2F70130H940410%2FFesto%2Ftree%2F112303537branchA) · [部署與資料搬移說明](docs/deployment.md)

同一網址提供 `/offline/` 離線協作版與 `/online/` 連線工廠版，各自保存資料與登入狀態。首次部署先提供測試資料；連線版需由管理者私下設定既有資料副本和 Supabase 憑證後啟用。`render.yaml` 使用付費 Starter 服務及 1 GB 持久化磁碟，請先核對主機顯示的費用。原本的本機資料庫不會被初始化工具修改或上傳至 GitHub。

## 新成員：下載後在本機執行

目前網站更新在 **`112303537branchA`** 分支。建議使用 **Python 3.11 或更新版本**。一般離線開發不需要 USB、Access、ODBC 驅動、Supabase 金鑰或 Node.js。

Windows PowerShell：

```powershell
git clone --branch 112303537branchA https://github.com/70130H940410/Festo.git
cd Festo/shopping_website
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe dev.py init
.\.venv\Scripts\python.exe dev.py run
```

如果使用其他已安裝的 Python 版本，將 `py -3.11` 改為對應的 Python 指令。以上直接使用虛擬環境內的 Python，不需更改 PowerShell 執行原則。

macOS／Linux（完成 clone 後）：

```sh
cd Festo/shopping_website
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-local.txt
.venv/bin/python dev.py init
.venv/bin/python dev.py run
```

開啟 **http://127.0.0.1:8768**。按 `Ctrl+C` 關閉本機示範，之後只需再執行 `dev.py run`，不用重新初始化。若連接埠已被使用，可加 `--port 8770`。

| 身分 | 帳號 | 密碼 |
| --- | --- | --- |
| 開發管理者 | `demo_admin` | `LocalDemo123!` |
| 測試顧客 | `demo_customer` | `LocalDemo123!` |

這些是公開的離線測試帳號，不是工廠帳號。管理者註冊示範金鑰為 `LOCAL-DEMO-ONLY`。不要把這組帳號或範例資料用在正式服務。

## 資料會放在哪裡

`dev.py init` **只建立新的** `shopping_website/.local-data/`，產生三個 SQLite 資料庫：`User_Data.db`、`product.db`、`order_management.db`。原本 `shopping_website/database/` 內的資料庫完全不動，也不複製任何真實帳號、訂單或工廠 Access 資料。

目錄只要已存在就會拒絕初始化，沒有覆寫選項。想試另一組資料時，選擇新的目錄，並在每個指令使用同一個路徑：

```powershell
.\.venv\Scripts\python.exe dev.py init --data-dir .local-data/experiment-2
.\.venv\Scripts\python.exe dev.py check --data-dir .local-data/experiment-2
.\.venv\Scripts\python.exe dev.py run --data-dir .local-data/experiment-2 --port 8770
```

`check` 以唯讀方式檢查初始化標記、schema 版本及 SQLite 完整性。初始化中斷時請使用另一個新目錄，不要拿原資料庫當作重設目標。`.festo-demo` 是離線識別標記，請保留。

## 可以測試什麼

- 三色商品、示範 BOM／外部供料庫存、九道製程。
- 三筆 `DEMO-*` 訂單：黑色兩件待模擬、藍色一件待付款、白色一件已完成；皆沒有 MES 工單號。
- 顧客下單與模擬付款、管理者檢視訂單／製程、四種排程比較及瀏覽器 CSV 匯出。
- `dev.py run` 啟動既有本機模擬器，已確認的本機訂單會推進；2D 預設「本機訂單進度」，也可切換「流程示範」。這些動畫不是實際工廠訊號。

離線模式即使繼承電腦上的 Supabase 設定，也不會建立雲端連線或開啟 MES Access；既有 `.env` 不會由 `dev.py run` 載入。實廠戰情室、32 格倉儲即時狀態、MES 製程清單與 MES 送單需要真實連線，在離線版顯示未連接／不可用，不用假資料冒充實際訊號。

## 結構與測試

| 路徑 | 用途 |
| --- | --- |
| `shopping_website/database/schema/*.sql` | 可版控的空資料表結構，baseline v1 |
| `shopping_website/database/seed_demo.sql` | 人工編寫的商品、BOM、製程與訂單測試資料 |
| `shopping_website/dev.py` | 新目錄初始化、唯讀檢查、離線啟動 |
| `shopping_website/.env.example` | 可選設定範本；快速開始不需複製它 |
| `shopping_website/core/` | 網站與資料存取功能 |
| `shopping_website/tests/` | 使用獨立暫存資料的測試 |

從 `shopping_website` 執行離線協作驗證：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_dev_init.py
```

測試涵蓋拒絕覆寫、登入下單、排程比較、本機進度完成、所有路由資料目錄一致，以及阻止外部連線。完整 MES 單元測試另需 `requirements.txt` 的套件（`pyodbc` 在 Linux 可能需要 unixODBC），可執行 `python -m unittest discover -s tests -p "test_*.py"`；動畫邏輯測試使用 Node.js 執行 `node --test tests/floor-cloud.test.mjs`。

2026-11-16 驗證：在不含原資料庫與 `.env` 的程式副本中，以全新虛擬環境只安裝 `requirements-local.txt`，通過初始化、唯讀檢查、3 項離線流程測試及 HTTP 登入／本機模擬檢查。完整環境另通過 30 項 Python 測試與既有動畫測試。這是本機開發驗證，未發送實廠工單。

## 與工廠協作

### AI 修改工具：Impeccable ＋ Ponytail

本專案搭配以下兩個技能；它們是開發時給 AI 的工作指引，不是網站的執行套件，不需加入 Flask 或部署依賴。

| 技能 | 在本專案的用途 | 官方來源／安裝說明 |
| --- | --- | --- |
| Impeccable | 介面層級、FESTO 風格一致性、響應式、鍵盤操作、可讀性及動畫呈現 | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) |
| Ponytail | 先理解資料流，再以最小完整修改解決問題，優先重用既有程式與原生能力 | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) · [安裝指南](https://github.com/DietrichGebert/ponytail/blob/main/INSTALL.md) |

目前維護者的 Codex 工作區已可使用兩者；技能位於工作區設定中，**下載本儲存庫不會自動安裝到協作者的 AI 工具**。新協作者請依官方說明，選擇自己使用的 Codex、Claude Code 或 Cursor 安裝方式，並確認工具已辨識技能。保留技能所需的參考文件與腳本，不只複製名稱或單一提示詞，也不要用上游範本覆蓋本專案的 `AGENTS.md`。

建議任務描述：

> 請依本專案 AGENTS.md 與 CONTRIBUTING.md 修改。介面工作使用 Impeccable，程式修改使用 Ponytail；先檢查既有功能和資料流，以最小完整改動完成，保留本機資料與工廠同步界線，最後檢查受影響的呼叫端並回報驗證結果。

純後端工作不必套用介面設計流程。提交前請檢查修改連帶影響到的檔案；若所安裝版本提供 `/ponytail-review` 可使用它，否則直接請 AI 依同樣原則進行 review。只載入 Ponytail 的 `SKILL.md`，不代表已安裝所有 review 指令或 hooks。程式行數與宣傳中的節省比例不是本專案驗收標準。

完整修改原則見 [CONTRIBUTING.md](CONTRIBUTING.md)，AI 專用入口見 [AGENTS.md](AGENTS.md)。

請先看 [協作原則](CONTRIBUTING.md)。離線初始化不是正式資料庫遷移工具，不要對既有資料庫執行 seed 或用測試資料覆蓋工廠資料。

- [既有 MES 下行送單流程](docs/mes-downlink-update.md)
- [實廠 2D 同步與定位限制](docs/factory-animation-sync.md)
- [3556 工單不插 USB 實測紀錄](docs/mes3556-no-usb-2026-11-15.md)

這些開發指令只啟動本機網站，不會部署或重啟工廠同步程式。資料庫二進位及 `.env` 不進 Git；停止追蹤不會清除過去 Git 提交中的歷史檔案。
