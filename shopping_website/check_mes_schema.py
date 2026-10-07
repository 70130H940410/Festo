import pyodbc
import os

db_path = "/workspace/tutorials/Festo/shopping_website/database/FestoMES.accdb"
conn_str = r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + db_path + ";"
conn = pyodbc.connect(conn_str)
cur = conn.cursor()

tables = [row.table_name for row in cur.tables(tableType='TABLE')]
print("=== Tables in FestoMES.accdb ===")
print([t for t in tables if not t.startswith("MSys")])

# 看看既有的 tblOrder
cur.execute("SELECT TOP 5 * FROM tblOrder ORDER BY ONo DESC")
cols = [col[0] for col in cur.description]
print("\n=== tblOrder Columns ===")
print(cols)
for r in cur.fetchall():
    print(dict(zip(cols, r)))

# 看看是否有 tblOrderPos
if "tblOrderPos" in tables:
    cur.execute("SELECT TOP 5 * FROM tblOrderPos ORDER BY ONo DESC")
    pcols = [col[0] for col in cur.description]
    print("\n=== tblOrderPos Columns ===")
    print(pcols)
    for r in cur.fetchall():
        print(dict(zip(pcols, r)))

# 看看是否有其他與 Order 相關的表
order_tables = [t for t in tables if "order" in t.lower()]
print("\n=== Order Related Tables ===", order_tables)

conn.close()
