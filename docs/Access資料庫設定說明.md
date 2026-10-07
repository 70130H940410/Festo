# 資料庫設定與雲端同步說明

## 概覽

本專案採用**「工廠端上傳、網站端純雲端」**的架構，解決了工廠內網限制與 Python 32/64 位元不相容的問題。

* **網站端 (`app.py`)**：100% 純雲端運作，只從 Supabase 讀取機台資料。不需要安裝 Access 引擎。
* **工廠端 (`sync_agent.py`)**：在機台旁邊的電腦執行，負責讀取 `FestoMES.accdb` 並每 3 秒同步到 Supabase。

---

## 1. 網站端設定 (純雲端)

網站不再直接連線本機的 Access 資料庫，而是透過 `SUPABASE_URL` 和 `SUPABASE_KEY` 抓取資料。
設定位置在 `啟動網站.vbs`：

```vbs
supabaseUrl = "https://xxxx.supabase.co"
supabaseKey = "sb_publishable_xxxx..."
```

---

## 2. 工廠端設定 (同步程式)

工廠電腦必須執行 `啟動同步程式.vbs` 來將資料推送至雲端。
此腳本具備**自動判斷機制**：

1. 預設尋找工廠真實路徑：`C:\MES4\FestoMES.accdb`
2. 若找不到，自動切換至本機測試庫：`shopping_website\database\FestoMES.accdb`

要修改路徑，請編輯 `啟動同步程式.vbs`：

```vbs
Dim festoDbPath
festoDbPath = "C:\MES4\FestoMES.accdb"   ' ← 若工廠檔案在不同位置，直接改這裡
```

---

## 需要修改的地方（共 1 處）

### 📝 啟動網站.vbs（根目錄）

找到標有 [修改點] 的區塊（約第 60 行），修改 estoDbPath 這一行：

`bs
' [修改點] Access 資料庫路徑 — 每台電腦只需改這一行
Dim festoDbPath
festoDbPath = "\\192.168.1.50\SharedFolder\FestoMES.accdb"  ' <-- 改這裡
`

> ✅ **只需改這一行，程式碼完全不用動。**

---

## 各種情境的設定方式

### 情境 A：Access 在本機專案資料夾（預設）

`bs
festoDbPath = appDir & "\database\FestoMES.accdb"
`

適用時機：開發測試、展示用，不連接真實工廠資料庫。

---

### 情境 B：Access 在工廠其他電腦（網路 UNC 路徑）

`bs
festoDbPath = "\\192.168.1.50\MES\FestoMES.accdb"
`

| 欄位 | 說明 |
|------|------|
| 192.168.1.50 | 放資料庫那台電腦的 IP（內網） |
| MES | 那台電腦設定的共享資料夾名稱 |
| FestoMES.accdb | 資料庫檔名 |

**前置條件：**
- 那台電腦必須已分享該資料夾
- 執行網站的電腦需有讀寫權限

---

### 情境 C：Access 在掛載的網路磁碟機

`bs
festoDbPath = "Z:\FestoMES.accdb"
`

適用時機：IT 已將網路磁碟機對應到固定代號（如 Z:），比 UNC 路徑更穩定，建議在固定工廠環境使用。

---

### 情境 D：每台電腦指向不同資料庫

如果工廠多台電腦各自有獨立的 Access 資料庫，每台電腦的 啟動網站.vbs 設不同路徑即可。
專案資料夾（shopping_website）本身不需要改。

---

## 常見錯誤與解法

### ❌ [ODBC Microsoft Access Driver] Cannot open database
- 原因：路徑錯誤，或 Access 檔案不存在
- 解法：確認 estoDbPath 路徑正確，且檔案確實存在

### ❌ [Microsoft][ODBC Driver Manager] Data source name not found
- 原因：未安裝 **Microsoft Access Database Engine**（ODBC 驅動）
- 解法：下載並安裝 Microsoft Access Database Engine 2016 Redistributable
  - https://www.microsoft.com/en-us/download/details.aspx?id=54920
  - ⚠️ 注意：需與 Python 位元數相符（兩者同為 64-bit 或 32-bit）

### ❌ 連線成功但資料不更新
- 原因：Access 不支援多人同時寫入，可能被另一個連線 lock 住
- 解法：確認同一時間只有一個程式開啟該 .accdb 檔案

### ⚠️ Warning: Failed to sync order to FestoMES.accdb
- 這個警告**不影響下單流程**，只是 Access 寫入失敗
- 通常是暫時性網路問題或檔案被 lock，重試即可

---

## 檔案結構對照

`
Festo/
├── 啟動網站.vbs          ← [修改點] festoDbPath 在這裡
├── shopping_website/
│   ├── core/
│   │   └── db.py         ← FESTO_DB_PATH 定義（通常不需改）
│   └── database/
│       └── FestoMES.accdb ← 本機預設位置（情境 A）
└── docs/
    └── Access資料庫設定說明.md  ← 本文件
`

---

## 總結

| 你想做什麼 | 改哪裡 |
|-----------|--------|
| 換 Access 資料庫位置 | 啟動網站.vbs 的 estoDbPath |
| 換預設 fallback 路徑 | core/db.py 的 FESTO_DB_PATH |
| 完全不用 Access | 不需改，連線失敗時程式不會中斷 |
