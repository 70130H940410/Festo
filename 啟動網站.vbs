Dim oShell, oFSO
Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

Dim scriptDir, appDir, venvDir, pythonExe, pipExe, appPath, reqPath
scriptDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
appDir    = scriptDir & "\shopping_website"
venvDir   = appDir & "\venv"
pythonExe = venvDir & "\Scripts\python.exe"
pipExe    = venvDir & "\Scripts\pip.exe"
appPath   = appDir & "\app.py"
reqPath   = appDir & "\requirements.txt"

' ── check app.py ─────────────────────────────────────────────────
If Not oFSO.FileExists(appPath) Then
    MsgBox "app.py not found: " & appPath, 16, "Error"
    WScript.Quit
End If

' ── first time: venv not exist → create + install ────────────────
If Not oFSO.FolderExists(venvDir) Then

    ' check system python
    If oShell.Run("cmd /c python --version", 0, True) <> 0 Then
        MsgBox "Python is not installed or not in PATH." & vbCrLf & _
               "Please install Python 3 from https://python.org" & vbCrLf & _
               "(Make sure to check 'Add to PATH')", 16, "Python Not Found"
        WScript.Quit
    End If

    ' create venv
    MsgBox "First time setup: creating virtual environment..." & vbCrLf & _
           "A window will open, please wait until it closes.", 64, "Setup"
    Dim ret1
    ret1 = oShell.Run("cmd /c cd /d """ & appDir & """ && python -m venv venv", 1, True)
    If ret1 <> 0 Or Not oFSO.FileExists(pipExe) Then
        MsgBox "Failed to create venv.", 16, "Error"
        WScript.Quit
    End If

    ' install requirements
    If oFSO.FileExists(reqPath) Then
        Dim ret2
        ret2 = oShell.Run("cmd /c """ & pipExe & """ install -r """ & reqPath & """", 1, True)
        If ret2 <> 0 Then
            MsgBox "pip install finished with warnings." & vbCrLf & _
                   "Trying to start anyway...", 48, "Warning"
        End If
    End If

    MsgBox "Setup complete! Starting website...", 64, "Done"
End If

' ── check python in venv ─────────────────────────────────────────
If Not oFSO.FileExists(pythonExe) Then
    MsgBox "venv is broken. Delete the 'venv' folder and try again.", 16, "Error"
    WScript.Quit
End If

' =============================================================
' [修改點] Access 資料庫路徑 — 每台電腦只需改這一行
' -------------------------------------------------------------
' 那台電腦的路徑是 C:\MES4\FestoMES.accdb
' 但從這台電腦要用「網路路徑」才能存取：
'
'   步驟 1：去那台電腦，對 C:\MES4 按右鍵 → 共用 → 共用名稱設為 MES4
'   步驟 2：查那台電腦的 IP（cmd 輸入 ipconfig 查 IPv4）
'   步驟 3：把下方 IP 換成那台電腦的實際 IP
'
'   格式："\\<那台電腦IP>\<共用名稱>\FestoMES.accdb"
'   範例："\\192.168.1.50\MES4\FestoMES.accdb"
'
'   若已掛載網路磁碟機（如 Z:）：
'   festoDbPath = "Z:\MES4\FestoMES.accdb"
' =============================================================
Dim festoDbPath
'  ↓↓↓ 把 192.168.1.50 換成那台電腦的實際 IP ↓↓↓
festoDbPath = "\\192.168.1.50\MES4\FestoMES.accdb"  ' <== 改這裡

oShell.Environment("Process")("FESTO_DB_PATH") = festoDbPath

' =============================================================
' [修改點] Supabase 雲端設定（可選）
' -------------------------------------------------------------
' 去 supabase.com 建立免費專案後，把 URL 和 Key 填入下方。
' 填入後 Flask 會優先從雲端讀取 MES 資料。
' 留空（預設）則仍從本機 Access 讀取。
' =============================================================
Dim supabaseUrl, supabaseKey
supabaseUrl = "https://lgnzcudrhvqhiichmqis.supabase.co"
supabaseKey = "sb_publishable_yLkS2oqaUUEETl1ESDS9fg_8m2Uk9x4"

If supabaseUrl <> "" Then
    oShell.Environment("Process")("SUPABASE_URL") = supabaseUrl
    oShell.Environment("Process")("SUPABASE_KEY") = supabaseKey
End If

' ── start Flask ──────────────────────────────────────────────────
oShell.CurrentDirectory = appDir
oShell.Run "cmd /k """"" & pythonExe & """ """ & appPath & """""", 1, False

' ── open browser ─────────────────────────────────────────────────
WScript.Sleep 3000
oShell.Run "http://127.0.0.1:5000"
