from flask import Blueprint, render_template, jsonify, request
import sqlite3
import os
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def _db_path(filename):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "database", filename)

def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

@admin_bp.route('/dashboard')
def dashboard():
    return render_template('admin/dashboard.html')

@admin_bp.route('/api/status')
def api_status():
    order_db = _conn(_db_path("order_management.db"))
    prod_db = _conn(_db_path("product.db"))
    try:
        try:
            order_db.execute("ALTER TABLE station_state ADD COLUMN is_error INTEGER DEFAULT 0")
            order_db.commit()
        except Exception:
            pass
            
        # Get machine status
        stations = [dict(r) for r in order_db.execute("SELECT * FROM station_state").fetchall()]
        # ensure is_error defaults to 0 if null
        for s in stations:
            s['is_error'] = s.get('is_error') or 0
        
        # Get raw materials
        materials = [dict(r) for r in prod_db.execute("SELECT * FROM raw_materials").fetchall()]
        
        # Get shipping purchase orders
        purchases = []
        try:
            purchases = [dict(r) for r in prod_db.execute("SELECT material_id, quantity, expected_arrival FROM purchase_orders WHERE status='shipping'").fetchall()]
        except sqlite3.OperationalError:
            pass
        
        # Get active orders
        orders = [dict(r) for r in order_db.execute("SELECT order_id, customer_name, product, amount, status, date FROM order_list WHERE status IN ('active', 'pending_payment') ORDER BY date DESC").fetchall()]
        
        return jsonify({
            "stations": stations,
            "materials": materials,
            "purchases": purchases,
            "orders": orders,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    finally:
        order_db.close()
        prod_db.close()

@admin_bp.route('/api/restock', methods=['POST'])
def restock():
    prod_db = _conn(_db_path("product.db"))
    try:
        prod_db.execute("UPDATE raw_materials SET stock = 2000")
        prod_db.commit()
        
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))
        return jsonify({"success": True})
    finally:
        prod_db.close()

@admin_bp.route('/api/break', methods=['POST'])
def break_machine():
    data = request.get_json()
    station = data.get("station")
    order_db = _conn(_db_path("order_management.db"))
    try:
        try:
            order_db.execute("ALTER TABLE station_state ADD COLUMN is_error INTEGER DEFAULT 0")
        except Exception:
            pass
        order_db.execute("UPDATE station_state SET is_error = 1 WHERE station = ?", (station,))
        order_db.commit()
        
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))
        return jsonify({"success": True})
    finally:
        order_db.close()

@admin_bp.route('/api/repair', methods=['POST'])
def repair_machine():
    data = request.get_json()
    station = data.get("station")
    order_db = _conn(_db_path("order_management.db"))
    try:
        order_db.execute("UPDATE station_state SET is_error = 0 WHERE station = ?", (station,))
        order_db.commit()
        
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))
        return jsonify({"success": True})
    finally:
        order_db.close()

@admin_bp.route('/api/analytics', methods=['GET'])
def analytics():
    order_db = _conn(_db_path("order_management.db"))
    try:
        # 1. Order Status Distribution (Pie Chart)
        status_counts = order_db.execute("""
            SELECT status, COUNT(*) as c
            FROM order_list
            GROUP BY status
        """).fetchall()
        
        status_data = {
            "labels": [r['status'] for r in status_counts],
            "values": [r['c'] for r in status_counts]
        }
        
        # 2. Daily Completed Orders (Line Chart)
        daily_counts = order_db.execute("""
            SELECT date(date) as d, COUNT(*) as c
            FROM order_list
            WHERE status = 'completed'
            GROUP BY date(date)
            ORDER BY d ASC
            LIMIT 7
        """).fetchall()
        
        daily_data = {
            "labels": [r['d'] for r in daily_counts],
            "values": [r['c'] for r in daily_counts]
        }
        
        return jsonify({
            "status_pie": status_data,
            "daily_line": daily_data
        })
    finally:
        order_db.close()

