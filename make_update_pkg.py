import os
import shutil
import zipfile

SOURCE_FESTO = "/workspace/tutorials/Festo"
SOURCE_LINE = "/workspace/tutorials/Line_Talker"

TARGET_DIR = "/workspace/Festo_Cloud_Update"
ZIP_PATH = "/workspace/Festo_Cloud_Update.zip"

print("1. Preparing target directory:", TARGET_DIR)
if os.path.exists(TARGET_DIR):
    shutil.rmtree(TARGET_DIR)
os.makedirs(TARGET_DIR, exist_ok=True)

# 複製主要檔案
def ignore_patterns(path, names):
    ignored = set()
    for name in names:
        if name in ["__pycache__", ".git", "venv", ".pytest_cache", "scratch", "tunnel_festo.log", "test_*.py"]:
            ignored.add(name)
        elif name.endswith(".pyc"):
            ignored.add(name)
    return ignored

print("2. Copying shopping_website...")
shutil.copytree(
    os.path.join(SOURCE_FESTO, "shopping_website"),
    os.path.join(TARGET_DIR, "shopping_website"),
    ignore=ignore_patterns
)

print("3. Copying Line_Talker...")
shutil.copytree(
    SOURCE_LINE,
    os.path.join(TARGET_DIR, "Line_Talker"),
    ignore=ignore_patterns
)

print("4. Copying root scripts...")
root_files = [
    "啟動同步程式.vbs",
    "啟動網站.vbs",
    "啟動網站.bat",
]
for rf in root_files:
    src_file = os.path.join(SOURCE_FESTO, rf)
    if os.path.exists(src_file):
        shutil.copy2(src_file, os.path.join(TARGET_DIR, rf))

# 同時在根目錄放一份 sync_agent.py 方便在工廠電腦直接點擊執行
shutil.copy2(
    os.path.join(SOURCE_FESTO, "shopping_website", "sync_agent.py"),
    os.path.join(TARGET_DIR, "sync_agent.py")
)

# 建立更新說明檔
readme_content = """=============================================================
  Festo 雲端更新套件 (Festo_Cloud_Update)
  更新時間: 2026-09-18
=============================================================

【本次重大更新內容】
1. 工廠訂單自動推回與機台運作閉環：
   - 資料庫訂單（LINE 與網站）全自動下發至工廠 MES 主表 (tblOrder/tbl_order)
   - 自動生成工廠工單編號 (ONo: 3500+)，設定 State=1 (排產待加工)
   - 機台自動接單排程運轉，工序逐步推進 (pending -> running -> finished)
   - 完工後自動回寫 Supabase line_orders (Completed) 與 tbl_order (State=3)

2. 工廠端即時雙向同步程式 (sync_agent.py)：
   - 修正 Supabase 連線憑證
   - 強化時間對齊 (Time Alignment) 與 ASRS 32格立體倉儲 (tblBufferPos)
   - 支援將雲端訂單自動下行寫入工廠本機 FestoMES.accdb 的 tblOrder

3. LineTalker 查詢功能增強：
   - 支援一次查詢名下所有歷史訂單
   - 即時反饋工廠機台與百分比進度 (例如: 產線實時進度 22%, 正在 視覺檢測站)
   - 修正修改收件資訊邏輯，確認才成立訂單

【工廠現場使用步驟】
1. 將此資料夾內的所有內容，複製並覆蓋至工廠電腦隨身碟 E:\\Festo_Cloud_Update
2. 在工廠機台旁電腦雙擊執行「啟動同步程式.vbs」即可開始即時雙向同步！
=============================================================
"""

with open(os.path.join(TARGET_DIR, "更新說明與使用指南.txt"), "w", encoding="utf-8") as f:
    f.write(readme_content)

print("5. Creating ZIP archive:", ZIP_PATH)
if os.path.exists(ZIP_PATH):
    os.remove(ZIP_PATH)

with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, TARGET_DIR)
            zipf.write(full_path, arcname=os.path.join("Festo_Cloud_Update", rel_path))

# 同步複製一份到 /workspace/tutorials/Festo
tut_target = "/workspace/tutorials/Festo/Festo_Cloud_Update"
if os.path.exists(tut_target):
    shutil.rmtree(tut_target)
shutil.copytree(TARGET_DIR, tut_target)
shutil.copy2(ZIP_PATH, "/workspace/tutorials/Festo/Festo_Cloud_Update.zip")

print("All done! Festo_Cloud_Update generated successfully.")
