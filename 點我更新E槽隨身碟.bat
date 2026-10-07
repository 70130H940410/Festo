@echo off
chcp 65001 >nul
title Festo 隨身碟 E: 一鍵更新工具
echo ========================================================
echo   正在更新隨身碟 E:\Festo_Cloud_Update ...
echo   請稍候，系統正在從雲端通道下載並解壓覆蓋...
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Host '雲端下載中...' -ForegroundColor Cyan; Invoke-WebRequest -Uri 'https://architecture-grab-guided-labour.trycloudflare.com/download/Festo_Cloud_Update.zip' -OutFile '$env:TEMP\Festo_Cloud_Update.zip'; Write-Host '正在解壓縮覆蓋到 E:\Festo_Cloud_Update ...' -ForegroundColor Cyan; Expand-Archive -Path '$env:TEMP\Festo_Cloud_Update.zip' -DestinationPath 'E:\' -Force; Remove-Item '$env:TEMP\Festo_Cloud_Update.zip'; Write-Host '完成！' -ForegroundColor Green"

echo.
echo ========================================================
echo   [OK] 更新完成！E:\Festo_Cloud_Update 已更新至最新版本！
echo   隨身碟根目錄 Python 環境保持原樣，無任何改動。
echo ========================================================
echo.
pause
