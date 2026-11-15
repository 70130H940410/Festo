# 已使用的本機 Python 安裝工具（2026-11-15）

這裡保存當日實際使用成功的 `install_local_python_v2.py` 與 `.cmd`。這是有現場前置條件的部署紀錄，不是可在任何電腦直接執行的通用安裝器。此 Git 保存動作沒有再次執行安裝器。

當日從工廠已能工作的 Python 3.11.4、標準庫、DLL 與套件複製約 108 MiB，不重新下載套件。安裝器讀取使用者家目錄的 `FestoSync_CompletionCopy`，建立新的 `FestoSync_Standalone`，不覆蓋既有目的資料夾；複製原接收回條與 agent 身分以避免重送。它使用 `-I` 清除外部 Python 路徑，並唯讀查核正式 MES 歸檔工單 3555。

前置條件包括原完成同步副本、原 VBS 啟動檔、接收回條 SQLite、既有 pyodbc／Supabase 套件、Access ODBC 驅動，以及 `C:\MES4\FestoMES.accdb`。`.cmd` 當時與 USB `shopping_website` 目錄並排，使用該目錄下已能執行的 venv 啟動；不能直接從這個 Git 目錄當成通用啟動器執行。程式含現場 H 槽來源與 3555 驗證條件，重用前需重新核對。

安裝後啟動檔改用自身目錄下的 `Python\python.exe`。本機版本最初在 `C:\Users\Festo\FestoSync_Standalone`，目前實測位置為 `D:\112303555\FestoSync_Standalone`，入口為 `StartSync_Standalone.vbs`。

原 VBS 包含現場連線設定，因此不進 Git；Python 二進位、套件目錄與接收回條資料庫也不進 Git。原工作程式保留，只能啟動其中一份。

完整結果見 [3556 不插 USB 實測](../../../docs/mes3556-no-usb-2026-11-15.md)。
