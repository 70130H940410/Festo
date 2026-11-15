import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mes_dispatch as mes
from core import order_dispatch as web


class Query:
    def __init__(self, sb, table):
        self.sb, self.table, self.filters, self.changes = sb, table, [], None
    def select(self, *_): return self
    def order(self, *_): return self
    def limit(self, *_): return self
    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self
    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self
    def update(self, values):
        self.changes = values
        return self
    def insert(self, values):
        self.sb.tables[self.table].append({**values, 'id': 99})
        self.filters.append(lambda row: row['id'] == 99)
        return self
    def execute(self):
        rows = [r for r in self.sb.tables[self.table] if all(f(r) for f in self.filters)]
        if self.changes:
            if self.sb.fail_ack and self.changes.get('status', '').startswith('In Production'):
                self.sb.fail_ack = False
                raise OSError('cloud ack lost')
            for row in rows: row.update(self.changes)
        return SimpleNamespace(data=copy.deepcopy(rows))


class Cloud:
    def __init__(self):
        self.fail_ack = False
        self.tables = {'line_orders': [{'id': 7, 'status': 'Pending Payment', 'items': json.dumps({'web_order_id': 'test'})}]}
    def table(self, table): return Query(self, table)


def template_db():
    db = sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE tblSqlQuery(MClass,MNo,Short);
    INSERT INTO tblSqlQuery VALUES(101,2,'SetNewOrder');
    CREATE TABLE tblWorkPlanDef(WPNo,Type); INSERT INTO tblWorkPlanDef VALUES(1211,1);
    CREATE TABLE tblStepDef(WPNo,StepNo,NextStepNo,FirstStep,ResourceID,OpNo);
    INSERT INTO tblStepDef VALUES(1211,10,20,1,3,213),(1211,20,0,0,6,115);
    CREATE TABLE tblStepParameterDef(WPNo,StepNo,ParameterNo,Parameter);
    INSERT INTO tblStepParameterDef VALUES(1211,10,3,'210');
    CREATE TABLE tblOrder(ONo); INSERT INTO tblOrder VALUES(88);
    CREATE TABLE tblOrderPos(ONo,WPNo,StepNo,ResourceID,OpNo);
    INSERT INTO tblOrderPos VALUES(88,1211,10,3,213),(88,1211,20,6,115);''')
    return db


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.order = dict(order_id='test', product='Basic Fuse Box - Black x 2', amount=2, step_name='1 -> 2')
        self.payload = mes.build_payload(self.order, [1211])
        self.path = Path(self.temp.name) / 'orders.db'
        db = sqlite3.connect(self.path)
        db.executescript('''CREATE TABLE order_list(order_id,product,amount,step_name,status,mes_ono,supabase_order_id);
          INSERT INTO order_list VALUES('test','Basic Fuse Box - Black x 2',2,'1 -> 2','active',NULL,7);''')
        db.close()
        self.sb = Cloud()
    def tearDown(self): self.temp.cleanup()
    def db(self):
        db = sqlite3.connect(self.path); db.row_factory = sqlite3.Row; return db

    def test_template_color_and_route_validation(self):
        db = template_db()
        mes.validate_factory_templates(db, self.payload)
        blue = mes.build_payload({**self.order, 'product': 'Basic Fuse Box - Blue x 2'}, [1211])
        with self.assertRaisesRegex(ValueError, '410'): mes.validate_factory_templates(db, blue)
        wrong = {**self.payload, 'resources': [3,7]}
        with self.assertRaisesRegex(ValueError, '順序'): mes.validate_factory_templates(db, wrong)
        db.close()

    def test_confirmed_website_to_agent_and_receipt_retry(self):
        with patch.object(web, 'get_order_mgmt_db', side_effect=self.db), patch.object(web, 'get_supabase_client', return_value=self.sb):
            web.queue_order('test', [1211])
            self.assertEqual(self.sb.tables['line_orders'][0]['status'], mes.READY)
            with self.assertRaises(ValueError): web.queue_order('test', [1211])
        journal = Path(self.temp.name) / 'receipt.db'
        self.sb.fail_ack = True
        with patch.object(mes, 'mes_create_order', return_value=88) as send:
            with self.assertRaises(OSError): mes.sync_ready_orders(self.sb, template_db, journal)
            mes.sync_ready_orders(self.sb, template_db, journal)
            mes.sync_ready_orders(self.sb, template_db, journal)
            self.assertEqual(send.call_count, 1, 'Cloud ack retry must never create another order')
        result = self.sb.tables['line_orders'][0]
        self.assertIn('MES ONo: 88', result['status'])
        self.assertEqual(json.loads(result['items'])['mes_receipts'][0]['quantity'], 2)

    def test_only_confirmed_orders_and_legacy_cloud_not_replayed(self):
        db = self.db(); db.execute("UPDATE order_list SET status='pending_payment'"); db.commit(); db.close()
        with patch.object(web, 'get_order_mgmt_db', side_effect=self.db), patch.object(web, 'get_supabase_client', return_value=self.sb):
            with self.assertRaises(ValueError): web.queue_order('test', [1211])
            db = self.db(); db.execute("UPDATE order_list SET status='active'"); db.commit(); db.close()
            self.sb.tables['line_orders'][0]['status'] = 'Confirmed'
            web.queue_order('test', [1211])
            self.assertEqual(self.sb.tables['line_orders'][0]['status'], 'Confirmed')
            db = self.db(); self.assertIn('舊版', db.execute('SELECT mes_dispatch_error FROM order_list').fetchone()[0]); db.close()

    def test_header_without_positions_does_not_report_success_or_resend(self):
        def header_only():
            db = template_db()
            db.execute('DELETE FROM tblOrderPos')
            return db
        row = self.sb.tables['line_orders'][0]
        row.update(status=mes.READY, items=json.dumps({'mes_dispatch': self.payload}))
        journal = Path(self.temp.name) / 'records.db'
        with patch.object(mes, 'mes_create_order', return_value=88) as send:
            mes.sync_ready_orders(self.sb, header_only, journal)
            self.assertEqual(row['status'], 'MES Needs Review')
            self.assertIn('tblOrderPos', json.loads(row['items'])['mes_dispatch_error'])
            self.assertEqual(json.loads(row['items'])['mes_receipts'][0]['ono'], 88)
            row['status'] = mes.READY
            mes.sync_ready_orders(self.sb, template_db, journal)
            self.assertEqual(send.call_count, 1)
            self.assertTrue(json.loads(row['items'])['mes_receipts'][0]['records_verified'])

    def test_positions_require_header_correct_workplan_and_known_operation(self):
        for sql in ('DELETE FROM tblOrder', 'UPDATE tblOrderPos SET WPNo=4010', 'UPDATE tblOrderPos SET OpNo=999'):
            with self.subTest(sql=sql):
                db = template_db(); db.execute(sql)
                with self.assertRaises(ValueError):
                    mes.verify_order_records(db, [dict(ono=88, wp_no=1211)])
                db.close()

    def test_mes_current_step_is_sufficient_without_future_positions(self):
        for keep in (10, 20):
            db = template_db()
            db.execute('DELETE FROM tblOrderPos WHERE StepNo<>?', (keep,))
            receipt = dict(ono=88, wp_no=1211)
            mes.verify_order_records(db, [receipt])
            self.assertTrue(receipt['records_verified'])
            self.assertEqual(receipt['position_count'], 1)
            db.close()

    def test_uncertain_send_never_retries_even_after_restart(self):
        path = Path(self.temp.name) / 'receipts.db'
        with patch.object(mes, 'mes_create_order', side_effect=TimeoutError) as send:
            db = mes.open_journal(path)
            with self.assertRaises(ValueError): mes.dispatch_lines(db, 7, self.payload, lambda line: send(line))
            db.close(); db = mes.open_journal(path)
            with self.assertRaises(ValueError): mes.dispatch_lines(db, 7, self.payload, lambda line: send(line))
            self.assertEqual(send.call_count, 1)
            db.close()

    def test_all_lines_checked_before_any_mes_send(self):
        payload = copy.deepcopy(self.payload)
        payload['lines'].append(dict(product_name='Basic Fuse Box - Blue', raw_pno=410, quantity=1, wp_no=1211))
        row = self.sb.tables['line_orders'][0]
        row.update(status=mes.READY,items=json.dumps({'mes_dispatch': payload}))
        with patch.object(mes, 'mes_create_order') as send:
            mes.sync_ready_orders(self.sb, template_db, Path(self.temp.name)/'receipts.db')
            send.assert_not_called()
        self.assertEqual(row['status'], 'MES Needs Review')

    def test_socket_frame_and_fragmented_reply(self):
        class Socket:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def settimeout(self,*_): pass
            def sendall(self, data):
                self.data = data
            def recv(self,*_): return next(self.chunks)
        sock=Socket(); sock.chunks=iter([b'444;MClass=101;MNo=2;',b'ErrorState=0;ONo=88\r'])
        with patch('socket.create_connection', return_value=sock):
            self.assertEqual(mes.mes_create_order(self.payload['lines'][0],'test',2000),88)
        self.assertEqual(sock.data,b'444;MClass=101;MNo=2;#PNo=0;#WPNo=1211;#Aux1Int=2*')

    def test_partial_acceptance_remains_visible(self):
        payload=copy.deepcopy(self.payload)
        payload['lines'].append(copy.deepcopy(payload['lines'][0]))
        row=self.sb.tables['line_orders'][0]
        row.update(status=mes.READY,items=json.dumps({'mes_dispatch':payload}))
        with patch.object(mes,'mes_create_order',side_effect=[88,TimeoutError]) as send:
            mes.sync_ready_orders(self.sb,template_db,Path(self.temp.name)/'receipts.db')
            mes.sync_ready_orders(self.sb,template_db,Path(self.temp.name)/'receipts.db')
            self.assertEqual(send.call_count,2)
        self.assertEqual(row['status'],'MES Needs Review')
        self.assertEqual(json.loads(row['items'])['mes_receipts'][0]['ono'],88)

    def test_mes_failure_preserves_phase_raw_reply_and_never_replays(self):
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def settimeout(self, *_): pass
            def sendall(self, data): pass
            def recv(self, *_):
                return b'444;MClass=101;MNo=2;ErrorState=7;ONo=0\r'
        row = self.sb.tables['line_orders'][0]
        row.update(status=mes.READY, items=json.dumps({'mes_dispatch': self.payload}))
        journal = Path(self.temp.name)/'diagnostic.db'
        with patch.object(mes.socket, 'create_connection', return_value=Socket()) as connect:
            mes.sync_ready_orders(self.sb, template_db, journal)
            mes.sync_ready_orders(self.sb, template_db, journal)
            self.assertEqual(connect.call_count, 1)
        error = json.loads(row['items'])['mes_dispatch_error']
        self.assertIn('phase=parse', error)
        self.assertIn('ErrorState=7', error)
        with sqlite3.connect(journal) as db:
            saved = db.execute('SELECT state,error FROM receipts').fetchone()
        self.assertEqual(saved, ('uncertain', error))

    def test_connection_failure_and_partial_timeout_are_distinguishable(self):
        with patch.object(mes.socket, 'create_connection', side_effect=ConnectionRefusedError('refused')):
            with self.assertRaisesRegex(ValueError, 'phase=connect.*ConnectionRefusedError'):
                mes.mes_create_order(self.payload['lines'][0], 'test', 2000)
        class Socket:
            def __init__(self): self.count = 0
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def settimeout(self, *_): pass
            def sendall(self, data): pass
            def recv(self, *_):
                self.count += 1
                if self.count == 1: return b'444;MClass=101;'
                raise TimeoutError('timed out')
        with patch.object(mes.socket, 'create_connection', return_value=Socket()):
            with self.assertRaisesRegex(ValueError, "phase=receive.*response=b'444;MClass=101;'"):
                mes.mes_create_order(self.payload['lines'][0], 'test', 2000)

    def test_manager_post_requires_csrf(self):
        from app import create_app
        with create_app().test_client() as client:
            with client.session_transaction() as session:
                session['user_id']=1; session['role']='admin'
            self.assertEqual(client.post('/manager/orders/test/send-to-mes').status_code,403)

    def test_checkout_never_dispatches_and_payment_only_awaits_plan(self):
        from app import create_app
        from core import order_routes
        # Isolated copies; real warehouse, cloud and factory connections are mocked.
        source = Path(__file__).resolve().parents[1] / 'database'
        orders = Path(self.temp.name) / 'checkout.db'
        products = Path(self.temp.name) / 'products.db'
        shutil.copyfile(source/'order_management.db', orders)
        shutil.copyfile(source/'product.db', products)
        def connect(path):
            db=sqlite3.connect(path);db.row_factory=sqlite3.Row;return db
        with patch.object(order_routes,'get_order_mgmt_db',side_effect=lambda:connect(orders)), patch.object(order_routes,'get_product_db',side_effect=lambda:connect(products)), patch('core.db.get_supabase_client',return_value=self.sb), patch('core.db.get_festo_db') as factory, patch('core.mes_data_service.MesDataService.get_unified_products',return_value=[{'name':'Basic Fuse Box - Black','stock':10}]):
            with create_app().test_client() as client:
                with client.session_transaction() as session:
                    session['user_id']=1;session['account']='isolated-test';session['role']='user'
                    session['current_order_items']=[{'id':1,'name':'Basic Fuse Box - Black','quantity':1,'unit_price':100}]
                result=client.post('/api/submit_order',json={'selected_steps':list(range(1,10)),'contact_name':'test','contact_phone':'000','address':'test'})
                self.assertEqual(result.status_code,200,result.json)
                self.assertTrue(result.json['success'],result.json)
                cloud=self.sb.tables['line_orders'][-1]
                self.assertEqual(cloud['status'],'Pending Payment')
                order_id=json.loads(cloud['items'])['web_order_id']
                result=client.post('/api/pay_order/'+order_id)
                self.assertTrue(result.json['success'])
                self.assertEqual(cloud['status'],'MES Awaiting Plan')
                factory.assert_not_called()


if __name__ == '__main__': unittest.main()
