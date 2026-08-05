import sys
import os

# Add the parent directory or the current directory to sys.path so we can import core.db
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.db import get_festo_db, FESTO_DB_PATH

print("Attempting to connect to Access Database at:")
print(FESTO_DB_PATH)
print("File exists:", os.path.exists(FESTO_DB_PATH))

try:
    conn = get_festo_db()
    print("Successfully connected!")
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 1 ResourceID, ResourceName FROM tblResource")
    print("Sample resource:", cursor.fetchone())
    conn.close()
except Exception as e:
    print("\nError connecting to Access DB:")
    import traceback
    traceback.print_exc()
    
    import pyodbc
    print("\n--- Available ODBC Drivers on this system ---")
    drivers = pyodbc.drivers()
    if drivers:
        for driver in drivers:
            print(f"- {driver}")
    else:
        print("No ODBC drivers found!")
    
    print("\n💡 Tip: If you see no 'Microsoft Access Driver (*.mdb, *.accdb)' in the list above,")
    print("it means the Microsoft Access ODBC driver is not installed or bitness (32/64-bit) doesn't match your Python.")
    print("Please install 'Microsoft Access Database Engine 2016 Redistributable'.")

