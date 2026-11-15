"""Publish confirmed website orders to the existing line_orders downlink."""
import json
from .db import get_order_mgmt_db, get_supabase_client
from mes_dispatch import READY, build_payload, order_lines


def ensure_dispatch_schema(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(order_list)')}
    for name in ('mes_request', 'mes_dispatch_state', 'mes_dispatch_error', 'mes_receipts'):
        if name not in columns:
            db.execute(f'ALTER TABLE order_list ADD COLUMN {name} TEXT')
    db.commit()


def dispatch_view(order):
    view = dict(lines=[], plans=[], cloud_status=None, receipts=[], error=None)
    try:
        view['lines'] = order_lines(order['product'])
        sb = get_supabase_client()
        if sb is None:
            raise ValueError('尚未設定雲端連線。')
        view['plans'] = sb.table('tbl_work_plan_def').select('wp_no,description').order('wp_no').execute().data or []
        if order['supabase_order_id']:
            rows = sb.table('line_orders').select('status,items').eq('id', order['supabase_order_id']).limit(1).execute().data
            if rows:
                view['cloud_status'] = rows[0]['status']
                items = json.loads(rows[0]['items']) if isinstance(rows[0]['items'], str) else rows[0]['items']
                if isinstance(items, dict):
                    view['receipts'] = items.get('mes_receipts', [])
                    view['error'] = items.get('mes_dispatch_error')
        else:
            view['error'] = '此訂單尚無雲端訂單編號，需先修復原訂單同步。'
    except Exception as error:
        view['error'] = str(error) if isinstance(error, ValueError) else '讀取 MES 送單狀態失敗，請稍後重試。'
    return view


def queue_order(order_id, workplans):
    db = get_order_mgmt_db()
    try:
        ensure_dispatch_schema(db)
        db.execute('BEGIN IMMEDIATE')
        order = db.execute('SELECT * FROM order_list WHERE order_id=?', (order_id,)).fetchone()
        if order is None or order['status'] != 'active':
            raise ValueError('只可下發已確認且尚未取消／完成的訂單。')
        if order['mes_ono'] or order['mes_request']:
            raise ValueError('此訂單已有 MES 工單或下發請求，不重複下發。')
        if not order['supabase_order_id']:
            raise ValueError('缺少雲端訂單編號，請先修復訂單同步。')
        payload = build_payload(order, workplans)
        db.execute("UPDATE order_list SET mes_request=?,mes_dispatch_state='queued',mes_dispatch_error=NULL WHERE order_id=?",
                   (json.dumps(payload, ensure_ascii=False), order_id))
        db.commit()
    finally:
        db.close()
    publish_queued_orders(order_id)


def publish_queued_orders(order_id=None):
    sb = get_supabase_client()
    if sb is None:
        return 0
    db = get_order_mgmt_db()
    published = 0
    try:
        ensure_dispatch_schema(db)
        sql = "SELECT * FROM order_list WHERE mes_dispatch_state='queued' AND status='active'"
        rows = db.execute(sql + (' AND order_id=?' if order_id else ''), (order_id,) if order_id else ()).fetchall()
        for order in rows:
            try:
                remote = sb.table('line_orders').select('id,status,items').eq('id', order['supabase_order_id']).limit(1).execute().data
                if not remote:
                    raise ValueError('雲端原訂單不存在，未下發。')
                remote = remote[0]
                items = json.loads(remote['items']) if isinstance(remote['items'], str) else remote['items']
                if not isinstance(items, dict):
                    raise ValueError('舊版訂單格式需先核對，未下發。')
                payload = json.loads(order['mes_request'])
                # Cloud acknowledgement may have succeeded before a local interruption.
                if items.get('mes_dispatch') == payload and (remote['status'] == READY or remote['status'].startswith(('MES Dispatching:', 'In Production'))):
                    pass
                else:
                    if remote['status'] not in ('Pending Payment', 'MES Awaiting Plan'):
                        raise ValueError('此雲端訂單已有派工狀態或屬舊版，需先核對 MES，未重送。')
                    if items.get('web_order_id') != order['order_id']:
                        raise ValueError('雲端與網站訂單編號不一致，未下發。')
                    items['mes_dispatch'] = payload
                    result = sb.table('line_orders').update({'items': json.dumps(items, ensure_ascii=False), 'status': READY}).eq('id', remote['id']).eq('status', remote['status']).execute().data
                    if not result:
                        raise ValueError('雲端狀態已改變，請重新確認。')
                db.execute("UPDATE order_list SET mes_dispatch_state='published',mes_dispatch_error=NULL WHERE order_id=?", (order['order_id'],))
                db.commit()
                published += 1
            except Exception as error:
                message = str(error) if isinstance(error, ValueError) else '雲端送單未確認，可重試同步；不另建新工單。'
                db.execute('UPDATE order_list SET mes_dispatch_error=? WHERE order_id=?', (message, order['order_id']))
                db.commit()
    finally:
        db.close()
    return published
