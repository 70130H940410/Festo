import sys
import os

# Add parent directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.db import get_festo_db

try:
    conn = get_festo_db()
    cursor = conn.cursor()
    
    print("=== tblMachineReport latest timestamps ===")
    cursor.execute("SELECT MAX(TimeStamp) FROM tblMachineReport")
    print("Overall Max TimeStamp in tblMachineReport:", cursor.fetchone()[0])
    
    cursor.execute("SELECT ResourceID, MAX(TimeStamp), COUNT(*) FROM tblMachineReport GROUP BY ResourceID")
    print("Max TimeStamp per ResourceID:")
    for row in cursor.fetchall():
        print(f"  ResourceID: {row[0]}, Latest: {row[1]}, Count: {row[2]}")
        
    print("\n=== tblOrder latest dates ===")
    cursor.execute("SELECT MAX(PlanedStart), MAX(Start), MAX(End) FROM tblOrder")
    row = cursor.fetchone()
    print("Max PlanedStart:", row[0], "Max Start:", row[1], "Max End:", row[2])
    
    print("\n--- Latest 5 entries in tblMachineReport ---")
    cursor.execute("SELECT TOP 5 ID, ResourceID, TimeStamp, AutomaticMode, ManualMode, Busy, ErrorL0 FROM tblMachineReport ORDER BY TimeStamp DESC, ID DESC")
    columns = [column[0] for column in cursor.description]
    for row in cursor.fetchall():
        print(dict(zip(columns, row)))
        
    conn.close()
except Exception as e:
    import traceback
    traceback.print_exc()
