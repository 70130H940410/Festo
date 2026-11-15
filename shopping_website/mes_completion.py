"""Read MES's archived orders through the existing sync connection; never execute MES commands."""
import json

FIELDS = 'ONo, PlanedStart, PlanedEnd, Start, [End], State, Enabled, CNo'


def order_record(row, timestamp):
    return dict(ono=int(row[0]), planed_start=timestamp(row[1]), planed_end=timestamp(row[2]),
                start=timestamp(row[3]), end=timestamp(row[4]), state=row[5],
                enabled=bool(row[6]), cno=row[7])


def completed_receipts(items):
    """Require every dispatched line's verified receipt, not just the first MES number."""
    if not isinstance(items, dict):
        return []
    lines = (items.get('mes_dispatch') or {}).get('lines', [])
    receipts = items.get('mes_receipts', [])
    if not lines or len(lines) != len(receipts):
        return []
    by_line = {r.get('line_no'): r for r in receipts}
    if set(by_line) != set(range(len(lines))):
        return []
    for i, line in enumerate(lines):
        r = by_line[i]
        if (r.get('records_verified') is not True or type(r.get('ono')) is not int or r['ono'] <= 0
                or r.get('quantity') != line.get('quantity') or r.get('wp_no') != line.get('wp_no')):
            return []
    return receipts


def sync_finished_orders(sb, cur, state, timestamp):
    # Finished orders leave tblOrder. Only an archived header with End is completion evidence.
    cur.execute(f'SELECT TOP 100 {FIELDS} FROM tblFinOrder WHERE [End] IS NOT NULL '
                'AND ONo NOT IN (SELECT ONo FROM tblOrder) ORDER BY [End] DESC, ONo DESC')
    records = {int(r[0]): order_record(r, timestamp) for r in cur.fetchall()}
    orders = sb.table('line_orders').select('id,status,items').like('status', 'In Production%').execute().data or []
    ready = []
    for order in orders:
        try:
            items = json.loads(order['items']) if isinstance(order['items'], str) else order['items']
            receipts = completed_receipts(items)
        except (ValueError, TypeError, AttributeError):
            continue
        if not receipts:
            continue
        completed = []
        for receipt in receipts:
            # Targeted lookup also catches orders older than the latest 100 archived headers.
            cur.execute(f'SELECT {FIELDS} FROM tblFinOrder WHERE ONo=? AND [End] IS NOT NULL '
                        'AND ONo NOT IN (SELECT ONo FROM tblOrder)', (receipt['ono'],))
            row = cur.fetchone()
            if not row or row[3] is None or row[4] < row[3]:
                break
            record = order_record(row, timestamp)
            records[record['ono']] = record
            completed.append(record)
        if len(completed) == len(receipts):
            ready.append(order)
    snapshots = state.setdefault('finished_order_snapshots', {})
    pending = {ono: row for ono, row in records.items() if snapshots.get(ono) != row}
    if pending:
        sb.table('tbl_order').upsert(list(pending.values()), on_conflict='ono').execute()
        snapshots.update(pending)  # Retry failed uploads; do not advance before success.
        print(f'[+] tblFinOrder: {len(pending)} archived order headers updated')
    for order in ready:
        result = (sb.table('line_orders').update({'status': 'Completed'})
                  .eq('id', order['id']).eq('status', order['status'])
                  .eq('items', json.dumps(order['items'], ensure_ascii=False)).execute().data)
        if result:
            print(f"[+] Website order {order['id']}: Completed (all MES receipts archived)")
