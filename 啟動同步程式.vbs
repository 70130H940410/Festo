Dim oShell, oFSO
Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

Dim scriptDir, appDir, venvDir, pythonExe, pipExe, syncScript, reqPath
scriptDir  = oFSO.GetParentFolderName(WScript.ScriptFullName)
appDir     = scriptDir & "\shopping_website"
venvDir    = appDir & "\venv"
syncScript = appDir & "\sync_agent.py"
pythonExe  = venvDir & "\Scripts\python.exe"
pipExe     = venvDir & "\Scripts\pip.exe"
reqPath    = appDir & "\requirements.txt"

' =============================================================
' 檢查並建立虛擬環境 (VENV)
' =============================================================
If Not oFSO.FolderExists(venvDir) Or Not oFSO.FileExists(pythonExe) Then
    If oShell.Run("cmd /c python --version", 0, True) <> 0 Then
        MsgBox "Python is not installed or not in PATH." & vbCrLf & _
               "Please install Python 3 and check 'Add to PATH'.", 16, "Error"
        WScript.Quit
    End If

    MsgBox "Virtual environment (venv) is missing." & vbCrLf & _
           "We will now recreate it and install packages automatically." & vbCrLf & _
           "Please wait for the black window to close.", 64, "First Time Setup"
           
    oShell.Run "cmd /c cd /d """ & appDir & """ && python -m venv venv", 1, True
    
    If oFSO.FileExists(reqPath) Then
        oShell.Run "cmd /c """ & pipExe & """ install -r """ & reqPath & """", 1, True
    End If
    
    If Not oFSO.FileExists(pythonExe) Then
        MsgBox "Failed to create virtual environment.", 16, "Error"
        WScript.Quit
    End If
End If
Dim festoDbPath
festoDbPath = "C:\MES4\FestoMES.accdb"

' =============================================================
' [智慧切換機制] 隨插即用設計
' 優先尋找工廠的真實機台資料庫 (C:\MES4)。
' 如果你把隨身碟插在自己筆電 (沒有 C:\MES4)，程式會自動退回使用測試資料庫。
' =============================================================
If Not oFSO.FileExists(festoDbPath) Then
    festoDbPath = scriptDir & "\shopping_website\database\FestoMES.accdb"
End If
' =============================================================
' [MODIFY HERE] Supabase settings
' =============================================================
Dim supabaseUrl, supabaseKey
supabaseUrl = "https://lgnzcudrhvqhiichmqis.supabase.co"
supabaseKey = "sb_publishable_yLkS2oqaUUEETl1ESDS9fg_8m2Uk9x4"

oShell.Environment("Process")("FESTO_DB_PATH") = festoDbPath
oShell.Environment("Process")("SUPABASE_URL")  = supabaseUrl
oShell.Environment("Process")("SUPABASE_KEY")  = supabaseKey

' Run sync agent (使用 cmd /k 讓黑視窗在發生錯誤時不會立刻閃退)
oShell.Run "cmd /k """"" & pythonExe & """ """ & syncScript & """""", 1, False
