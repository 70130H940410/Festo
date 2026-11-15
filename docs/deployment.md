# 同一網站：離線協作與連線工廠

`shopping_website/deploy.py` 用 Waitress 啟動同一個網站，入口 `/` 可選擇 `/offline/` 或 `/online/`。兩者共用程式與外觀，但資料庫、登入 Cookie、簽章金鑰、MES 快取及 SSE 即時通知各自獨立。同時開兩種模式的分頁，不會因為切換選單而把另一個分頁的訂單送錯地方。

「離線」是指不連 MES／Supabase；使用雲端網址仍需要網路。沒有網路時，使用 README 的本機 `dev.py run`。本次沒有加入 PWA 或瀏覽器離線資料同步。

## 直接部署到 Render

[開啟部署設定](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2F70130H940410%2FFesto%2Ftree%2F112303537branchA)

1. 登入自己的 Render 帳號，連接 GitHub 儲存庫，使用 `112303537branchA` 分支的 `render.yaml`。
2. 檢查服務與費用後建立部署。設定使用 **Starter 付費 Web Service + 1 GB persistent disk**，不是免費方案；金額以 Render 建立服務時顯示為準。
3. 首次啟動自動在 `/var/data/festo/offline` 建立測試資料。再次啟動只驗證與使用已有資料，不重設。若檢查失敗會停止啟動，不刪除資料。
4. 在 Render 顯示的 HTTPS 網址開啟入口。初始僅啟用離線版；連線版顯示尚未啟用，並非假裝已接上工廠。

根據 [Render 官方持久化磁碟說明](https://render.com/docs/disks)，只有磁碟掛載路徑下的檔案會跨重啟／部署保存；本設定把兩種資料都放在 `/var/data`。不要移除磁碟，也不要把資料改放在程式碼目錄。自動部署預設關閉，避免每次 GitHub 更新都直接替換協作者的服務；需要時在自己的服務手動部署已確認的版本。

## 啟用連線工廠版

雲端網站不執行工廠代理，也不需要 Windows Access 驅動。維持既有工廠電腦的同步程式運作，網站透過同一個 Supabase 專案交換已確認訂單及 MES 狀態。

1. 先安排網站資料切換時段，暫停舊網站新增／修改訂單。工廠同步代理維持原本那一份；不要另開第二份。
2. 從原網站的三個 SQLite 資料庫建立**副本**。在 `shopping_website` 執行：

   ```powershell
   python export_web_databases.py database .deployment-data/online
   ```

   來源以唯讀連線和 SQLite backup API 開啟，拒絕覆寫既有目的目錄；不複製 Access 或 `.env`。三個檔案依序備份，因此匯出期間不要在原網站寫資料，才能保持跨資料庫的一致性。這個目錄含真實帳號與訂單，僅透過主機的私密檔案傳輸放到 `/var/data/festo/online`，**不經 GitHub、不放在 static 目錄**。
3. 在主機環境變數設定 `SUPABASE_URL`、`SUPABASE_KEY`，使用工廠既有專案的伺服器憑證，不寫入 YAML／Git 或瀏覽器。設定 `FESTO_ONLINE_ENABLED=1`，保留原本自動產生的 `FESTO_SECRET_KEY`。
4. 開啟連線版前，確認正式管理者沒有使用 `123` 等測試密碼；公開 demo 帳號會被啟動檢查拒絕。用實際工廠帳號登入 `/online/login`，先核對工單與機台時間戳。查詢成功不等於設備運作正常，沒有新訊號時動畫仍應停止或顯示未知。
5. 驗證正式網址與原資料一致後，將使用者導向新網站；舊網站保留作備份但不再接受下單。兩份 SQLite 副本不會自動互相合併，不要讓使用者同時在新舊網站建立訂單。

實際送單仍走既有「付款確認 → 管理者確認 MES 製程 → 原同步程式 → MES 回條」，不由模式切換直接觸發下單。背景程式會繼續處理資料庫中已確認的待送請求，切換前須核對待送單及既有 MES 回條，不能把舊的資料副本重複當新訂單匯入。

連線模式缺少憑證、三個資料庫之一或資料完整性檢查失敗時，啟動會報錯，不會自動建立假正式資料。不要刪除 demo 標記或改帳號來把示範資料冒充正式資料。

## 自有 Python 主機／本機預覽雙模式

使用 Python 3.11，從 `shopping_website` 安裝 `requirements-deploy.txt`，設定：

| 環境變數 | 用途 |
| --- | --- |
| `FESTO_STORAGE_DIR` | 絕對路徑，使用可持久保存的獨立目錄 |
| `FESTO_SECRET_KEY` | 至少 32 字元的隨機值，重啟時保持不變 |
| `FESTO_ONLINE_ENABLED` | `0` 只提供離線版；`1` 啟用已有資料副本的連線版 |
| `FESTO_COOKIE_SECURE` | 線上 HTTPS 固定 `1`；只在本機 HTTP 預覽時使用 `0` |
| `PORT` | HTTP 監聽埠，預設 `8768` |

啟動 `python deploy.py`。前面必須由主機提供 HTTPS；不要用 Flask 開發伺服器提供正式服務。`/healthz` 僅代表網站程序可回應，**不代表 MES 已連線**。這個部署入口不讀本機 `.env`，請由主機設定環境變數。

目前採單一服務實例／單一程序，沿用既有背景排程器與 SQLite；不要擴展成多個實例或額外再啟動 worker，避免重複推進。SSE 長連線會占用 Waitress 執行緒，本配置適合小型協作；大量使用者需另行處理串流與資料庫擴展。

部署入口額外限制未登入管理 API、跨來源寫入與開發用重設端點；連線版關閉公開管理者註冊及直接修改機台故障旗標。其他本機啟動方式保留原行為。這些檢查不是完整的公開網路安全稽核，實際工廠版應再搭配組織的存取限制。

## 驗證

`python -m unittest discover -s tests -p "test_*.py"` 包含雙模式 Cookie、資料路徑、快取／推播隔離、跨來源寫入、持久化重啟及唯讀匯出測試。JavaScript 動畫另執行 `node --test tests/floor-cloud.test.mjs`。本次尚未在 Render 帳號部署，也未藉部署測試送出實廠工單。

2026-11-16 本機驗證：35 項 Python 測試及既有動畫測試通過；以 Waitress 實際啟動、登入離線版、讀取 2D 工單完成狀態與 SSE，瀏覽器未記錄 JavaScript 錯誤。原有四個資料庫 SHA-256 與修改前一致。
