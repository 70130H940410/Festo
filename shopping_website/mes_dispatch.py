"""Existing sync_agent's MES4 downlink. Standard library only; no extra agent."""
import hashlib
import json
import re
import socket
import sqlite3
import uuid
from datetime import datetime, timezone

READY = 'MES Ready v1'
RAW_PARTS = {'Basic Fuse Box - Black': 210, 'Basic Fuse Box - Blue': 410,
             'Basic Fuse Box - White': 610}
STEP_RESOURCES = {1: 3, 2: 6, 3: 7, 4: 5, 5: 4, 6: 1, 7: 2, 8: 8, 9: 3}


def order_lines(product):
    lines = []
    for value in product.split(', '):
        match = re.fullmatch(r'(.+) x ([1-9][0-9]*)', value)
        if not match or match[1] not in RAW_PARTS:
            raise ValueError('商品或數量尚無 MES 對照，請確認訂單品項。')
        lines.append(dict(product_name=match[1], quantity=int(match[2]), raw_pno=RAW_PARTS[match[1]]))
    return lines


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('缺少新版 MES 下發資料。')
    lines = payload.get('lines')
    if not isinstance(lines, list) or not lines:
        raise ValueError('訂單沒有品項。')
    for line in lines:
        if line.get('product_name') not in RAW_PARTS or line.get('raw_pno') != RAW_PARTS[line['product_name']]:
            raise ValueError('未加工料號與商品不一致。')
        for field in ('quantity', 'wp_no'):
            if type(line.get(field)) is not int or not 1 <= line[field] <= 32767:
                raise ValueError('數量或 MES 製程編號不正確。')
    resources = payload.get('resources')
    if not isinstance(resources, list) or not resources or any(type(r) is not int or r not in range(1, 9) for r in resources):
        raise ValueError('缺少已確認的製程順序。')
    return payload


def build_payload(order, workplans):
    lines = order_lines(order['product'])
    if len(lines) != len(workplans) or sum(r['quantity'] for r in lines) != order['amount']:
        raise ValueError('品項數量與訂單不一致。')
    try:
        resources = [STEP_RESOURCES[int(s.strip())] for s in order['step_name'].split('->')]
        for line, wp in zip(lines, workplans):
            line['wp_no'] = int(wp)
    except (ValueError, KeyError, TypeError):
        raise ValueError('請為每個品項選擇 MES 製程；不支援未知的網站製程。')
    return validate_payload(dict(version=1, web_order_id=order['order_id'], resources=resources, lines=lines))


def validate_factory_templates(connection, payload):
    """Verify local MES master data before sending any create-order command."""
    validate_payload(payload)
    cur = connection.cursor()
    service = cur.execute('SELECT [Short] FROM tblSqlQuery WHERE MClass=101 AND MNo=2').fetchone()
    if not service or service[0] != 'SetNewOrder':
        raise ValueError('MES 101/2 不是預期的 SetNewOrder 服務。')
    for line in payload['lines']:
        wp = line['wp_no']
        plan = cur.execute('SELECT [Type] FROM tblWorkPlanDef WHERE WPNo=?', (wp,)).fetchone()
        if not plan or plan[0] != 1:
            raise ValueError(f'WPNo {wp} 不是可用的固定製程，需在 MES 確認。')
        rows = cur.execute('SELECT StepNo,NextStepNo,FirstStep,ResourceID,OpNo FROM tblStepDef WHERE WPNo=?', (wp,)).fetchall()
        steps = {r[0]: r for r in rows}
        first = [r for r in rows if r[2]]
        if len(first) != 1:
            raise ValueError(f'WPNo {wp} 起始步驟不明確。')
        route, seen, number = [], set(), first[0][0]
        while number:
            if number in seen or number not in steps:
                raise ValueError(f'WPNo {wp} 製程鏈不完整。')
            seen.add(number)
            row = steps[number]
            route.append(row[3])
            number = row[1]
        if route != payload['resources']:
            raise ValueError(f'WPNo {wp} 與訂單製程順序不同，不下發。')
        # Verified ASRS release operations in the existing database use parameter 3 as the input part.
        if first[0][3] != 3 or first[0][4] not in (212, 213):
            raise ValueError(f'WPNo {wp} 不是已確認的 ASRS 出料製程。')
        raw = cur.execute('SELECT [Parameter] FROM tblStepParameterDef WHERE WPNo=? AND StepNo=? AND ParameterNo=3', (wp, first[0][0])).fetchone()
        if not raw or str(raw[0]).strip() != str(line['raw_pno']):
            raise ValueError(f"WPNo {wp} 的上料不是 {line['raw_pno']}，請在 MES 選用正確顏色製程。")


def mes_create_order(line, host, port):
    # Festo MES4 Interfaces v1.07: full string encoding; 101/2 SetNewOrder.
    packet = f"444;MClass=101;MNo=2;#PNo=0;#WPNo={line['wp_no']};#Aux1Int={line['quantity']}*".encode('ascii')
    data = bytearray()
    phase = "connect"
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.settimeout(10)
            phase = "send"
            sock.sendall(packet)
            phase = "receive"
            while b'\r' not in data and b'*' not in data:
                chunk = sock.recv(4096)
                if not chunk or len(data) + len(chunk) > 65536:
                    raise ValueError('MES 回覆未完成，接收結果須人工核對。')
                data.extend(chunk)
            phase = "parse"
            message = re.split(rb'[\r*]', bytes(data), maxsplit=1)[0].decode('ascii')
            parts = message.split(';')
            if parts[0] != '444':
                raise ValueError('MES 回覆格式錯誤，須核對是否已建單。')
            fields = dict(part.split('=', 1) for part in parts[1:] if '=' in part)
            if fields.get('MClass') != '101' or fields.get('MNo') != '2' or fields.get('ErrorState') != '0':
                raise ValueError('MES 回覆錯誤，須核對是否已建單。')
            ono = int(fields.get('ONo', '0'))
            if ono <= 0:
                raise ValueError('MES 未回傳有效工單編號。')
            return ono
    except Exception as error:
        # Preserve evidence: a missing/invalid reply cannot prove that MES did not create the order.
        detail = (f"phase={phase}; endpoint={host}:{port}; "
                  f"{type(error).__name__}: {error}; request={packet!r}; response={bytes(data[:2048])!r}")
        raise ValueError(detail) from error


def open_journal(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS agent(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts(cloud_id INTEGER, line_no INTEGER, digest TEXT NOT NULL,
        state TEXT NOT NULL, ono INTEGER, error TEXT, PRIMARY KEY(cloud_id,line_no));''')
    db.execute('INSERT OR IGNORE INTO agent VALUES(1,?)', (uuid.uuid4().hex,))
    db.commit()
    return db


def verify_order_records(connection, receipts):
    """An acknowledgement alone does not prove that MES created both tables."""
    cur = connection.cursor()
    for receipt in receipts:
        ono, wp = receipt['ono'], receipt['wp_no']
        header = cur.execute('SELECT ONo FROM tblOrder WHERE ONo=?', (ono,)).fetchone()
        positions = cur.execute('SELECT WPNo,StepNo,ResourceID,OpNo FROM tblOrderPos WHERE ONo=?', (ono,)).fetchall()
        expected = {tuple(r) for r in cur.execute('SELECT StepNo,ResourceID,OpNo FROM tblStepDef WHERE WPNo=?', (wp,)).fetchall()}
        actual = {tuple(r[1:]) for r in positions if r[0] == wp}
        # MES creates the current operation first, then advances it during execution;
        # a complete workplan does not mean all its steps exist in tblOrderPos at once.
        if not header or not actual or not actual.issubset(expected):
            raise ValueError(f'MES ONo {ono} 已回覆，但 tblOrder / tblOrderPos 對應未確認 '
                             f'(主檔={bool(header)}, 明細={len(positions)}, WPNo={wp})；保留工單號，不重新建單。')
        receipt['records_verified'] = True
        receipt['position_count'] = len(positions)


def dispatch_lines(db, cloud_id, payload, send):
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    receipts = []
    for index, line in enumerate(payload['lines']):
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM receipts WHERE cloud_id=? AND line_no=?', (cloud_id, index)).fetchone()
        if old:
            if old['digest'] != digest:
                db.rollback()
                raise ValueError('下發資料已變更，禁止重新建立同一訂單。')
            if old['state'] not in ('accepted', 'retry_authorized'):
                db.rollback()
                raise ValueError('先前下發結果未確認，請核對 MES；不自動重送。 ' + (old['error'] or ''))
            if old['state'] == 'accepted':
                db.rollback()
                ono = old['ono']
            else:
                db.execute("UPDATE receipts SET state='sending' WHERE cloud_id=? AND line_no=?", (cloud_id, index))
        else:
            # Durable intent is recorded before any bytes can reach MES. Crash/timeout never blindly retries.
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,NULL,NULL)', (cloud_id, index, digest, 'sending'))
        if not old or old['state'] == 'retry_authorized':
            db.commit()
            try:
                ono = send(line)
            except Exception as error:
                message = 'MES 接收結果未確認；請人工核對，不自動重送。 ' + str(error)[:4096]
                db.execute("UPDATE receipts SET state='uncertain',error=? WHERE cloud_id=? AND line_no=?",
                           (message, cloud_id, index))
                db.commit()
                raise ValueError(message) from error
            db.execute("UPDATE receipts SET state='accepted',ono=? WHERE cloud_id=? AND line_no=?", (ono, cloud_id, index))
            db.commit()
        receipts.append(dict(line_no=index, ono=ono, product_name=line['product_name'], quantity=line['quantity'], wp_no=line['wp_no']))
    return receipts


def sync_ready_orders(sb, open_access, journal_path, host='127.0.0.1', port=2000):
    db = open_journal(journal_path)
    try:
        owned = 'MES Dispatching:' + db.execute('SELECT owner FROM agent WHERE id=1').fetchone()[0]
        orders = sb.table('line_orders').select('id,status,items').in_('status', [READY, owned]).order('id').limit(10).execute().data or []
        for order in orders:
            if order['status'] == READY:
                claimed = sb.table('line_orders').update({'status': owned}).eq('id', order['id']).eq('status', READY).execute().data
                if not claimed:
                    continue
            items = None
            try:
                items = json.loads(order['items']) if isinstance(order['items'], str) else order['items']
                payload = validate_payload(items.get('mes_dispatch'))
                conn = open_access()
                try:
                    validate_factory_templates(conn, payload)
                finally:
                    conn.close()
                receipts = dispatch_lines(db, order['id'], payload, lambda line: mes_create_order(line, host, port))
                conn = open_access()
                try:
                    verify_order_records(conn, receipts)
                finally:
                    conn.close()
            except (ValueError, TypeError, AttributeError) as error:
                message = str(error) if isinstance(error, ValueError) else 'MES 下發資料格式不正確。'
                blocked_items = dict(items) if isinstance(items, dict) else {}
                blocked_items['mes_dispatch_error'] = message
                accepted = db.execute("SELECT line_no,ono,digest FROM receipts WHERE cloud_id=? AND state='accepted' ORDER BY line_no", (order['id'],)).fetchall()
                if accepted:
                    original = blocked_items.get('mes_dispatch')
                    digest = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                    blocked_items['mes_receipts'] = []
                    for receipt in accepted:
                        details = {}
                        if receipt['digest'] == digest:
                            details = {k: original['lines'][receipt['line_no']][k] for k in ('product_name', 'quantity', 'wp_no')}
                        blocked_items['mes_receipts'].append(dict(line_no=receipt['line_no'], ono=receipt['ono'], **details))
                sb.table('line_orders').update({'status': 'MES Needs Review', 'items': json.dumps(blocked_items, ensure_ascii=False)}).eq('id', order['id']).eq('status', owned).execute()
                print(f"[MES] Cloud order {order['id']}: {message}")
                continue
            items['mes_receipts'] = receipts
            items['mes_received_at'] = datetime.now(timezone.utc).isoformat()
            items.pop('mes_dispatch_error', None)
            # Failed cloud acknowledgement retries only the acknowledgement; accepted journal entries are reused.
            status = f"In Production (MES ONo: {receipts[0]['ono']})" if len(receipts) == 1 else 'In Production (multiple MES orders)'
            sb.table('line_orders').update({'status': status, 'items': json.dumps(items, ensure_ascii=False)}).eq('id', order['id']).eq('status', owned).execute()
    finally:
        db.close()
