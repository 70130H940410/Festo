@echo off
chcp 65001 >nul
title Festo 工廠模擬系統

:: 用短路徑（8.3格式）避免中文目錄造成路徑解析失敗
set ROOT=%~dps0
set APP_DIR=%ROOT%shopping_website
set PYTHON=%ROOT%shopping_website\venv\Scripts\python.exe

echo [路徑確認]
echo ROOT    = %ROOT%
echo APP_DIR = %APP_DIR%
echo PYTHON  = %PYTHON%
echo.

if not exist "%PYTHON%" (
    echo X 找不到 python.exe：%PYTHON%
    pause
    exit /b
)
echo OK python.exe 找到

if not exist "%APP_DIR%\app.py" (
    echo X 找不到 app.py：%APP_DIR%\app.py
    pause
    exit /b
)
echo OK app.py 找到

echo.
echo 正在設定 Supabase 雲端環境變數...
set SUPABASE_URL=https://lgnzcudrhvqhiichmqis.supabase.co
set SUPABASE_KEY=sb_publishable_yLkS2oqaUUEETl1ESDS9fg_8m2Uk9x4

echo 正在啟動 Flask...
cd /d "%APP_DIR%"
start "" cmd /k ""%PYTHON%" app.py"

echo 等待伺服器就緒...
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5000

echo.
echo 按任意鍵關閉此視窗（Flask 仍繼續跑）...
pause >nul
