import sys
import os
from datetime import datetime

# Add parent directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.db import get_festo_db

print("Connecting to database...")
try:
    conn = get_festo_db()
    cursor = conn.cursor()
    print("Connected successfully!")
    
    print("\n--- Testing tblResource Query ---")
    cursor.execute("SELECT ResourceID, ResourceName FROM tblResource WHERE ResourceType IS NOT NULL OR ResourceName IS NOT NULL")
    resources = cursor.fetchall()
    print(f"Found {len(resources)} resources:")
    for r in resources:
        print(f"  ID: {r.ResourceID}, Name: {r.ResourceName}")
        
    print("\n--- Testing tblMachineReport Query ---")
    machines = []
    for r in resources:
        print(f"Querying report for ResourceID: {r.ResourceID}...")
        cursor.execute("SELECT TOP 1 AutomaticMode, ManualMode, Busy, ErrorL0 FROM tblMachineReport WHERE ResourceID = ? ORDER BY ID DESC", (r.ResourceID,))
        m = cursor.fetchone()
        if m:
            print(f"  Found report: AutomaticMode={m.AutomaticMode}, ManualMode={m.ManualMode}, Busy={m.Busy}, ErrorL0={m.ErrorL0}")
        else:
            print("  No report found.")
            
    print("\n--- Testing tblOrder Query ---")
    cursor.execute("""
        SELECT TOP 10 ONo, PlanedStart, PlanedEnd, Start, End, State
        FROM tblOrder
        ORDER BY ONo DESC
    """)
    order_cols = [column[0] for column in cursor.description]
    orders = [dict(zip(order_cols, row)) for row in cursor.fetchall()]
    print(f"Found {len(orders)} orders:")
    for o in orders:
        print(f"  ONo: {o['ONo']}, State: {o['State']}")
        
    conn.close()
    print("\nAll queries ran successfully!")
except Exception as e:
    print("\nError during queries:")
    import traceback
    traceback.print_exc()
