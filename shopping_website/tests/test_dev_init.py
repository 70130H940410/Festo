"""New-clone workflow uses synthetic data and cannot reach production services."""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev import DATABASES, DEMO_PASSWORD, create_demo_app, init_demo, validate_demo


class DemoInitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'demo'

    def test_initialization_refuses_existing_directory_and_preserves_bytes(self):
        init_demo(self.directory)
        before = {name: (self.directory / name).read_bytes() for name in DATABASES}
        with self.assertRaises(FileExistsError):
            init_demo(self.directory)
        self.assertEqual(before, {name: (self.directory / name).read_bytes() for name in DATABASES})
        validate_demo(self.directory)
        with closing(sqlite3.connect(self.directory / 'order_management.db')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM order_list').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM order_list WHERE mes_ono IS NOT NULL OR supabase_order_id IS NOT NULL').fetchone()[0], 0)
        with closing(sqlite3.connect(self.directory / 'User_Data.db')) as db:
            self.assertTrue(all(row[0].endswith('@example.invalid') for row in db.execute('SELECT email FROM User_profile')))

    def test_missing_or_unmarked_database_cannot_launch(self):
        with self.assertRaises(ValueError):
            validate_demo(self.directory)
        self.assertFalse(self.directory.exists())
        init_demo(self.directory)
        (self.directory / 'product.db').unlink()
        with self.assertRaises(sqlite3.OperationalError):
            validate_demo(self.directory)
        self.assertFalse((self.directory / 'product.db').exists())

    def test_offline_order_schedule_and_animation_workflow(self):
        init_demo(self.directory)
        original_dir = Path(__file__).resolve().parents[1] / 'database'
        originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original_dir.iterdir()
                     if p.suffix in ('.db', '.accdb')}
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://unused.example.invalid', 'SUPABASE_KEY': 'dummy-test-key'}), \
             patch('socket.socket.connect', side_effect=AssertionError('Offline demo attempted a network connection')):
            app = create_demo_app(self.directory)
            app.testing = True
            from core import db, admin_routes, factory_routes
            with app.app_context(), patch.object(db, '_supabase_client', object()):
                self.assertIsNone(db.get_supabase_client())  # Even a cached live client is blocked.
                with self.assertRaises(RuntimeError):
                    db.get_festo_db()
                for path_fn in (db.database_path, admin_routes._db_path, factory_routes._db_path):
                    self.assertEqual(Path(path_fn('product.db')), self.directory / 'product.db')
            browser = app.test_client()
            login = lambda account: browser.post('/login', data={'user_login': account, 'password': DEMO_PASSWORD})
            self.assertEqual(login('demo_customer').status_code, 302)
            self.assertEqual(browser.get('/order').status_code, 200)
            self.assertEqual(browser.post('/order', data={'qty_1': '1'}).status_code, 302)
            self.assertEqual(browser.get('/process-plan').status_code, 200)
            submitted = browser.post('/api/submit_order', json={'selected_steps': [1, 9], 'contact_name': 'Demo',
                                     'contact_phone': 'TEST-ONLY', 'address': 'Not shipped', 'note': 'offline test'})
            self.assertTrue(submitted.json['success'], submitted.json)
            with app.app_context(), closing(db.get_order_mgmt_db()) as orders:
                order = dict(orders.execute("SELECT * FROM order_list WHERE note='offline test'").fetchone())
                self.assertIsNone(order['supabase_order_id'])
                self.assertIsNone(order['mes_ono'])
            order_id = order['order_id']
            self.assertTrue(browser.post('/api/pay_order/' + order_id).json['success'])
            self.assertEqual(login('demo_admin').status_code, 302)
            for url in ('/', '/profile', '/orders', '/manager/orders', '/manager/inventory',
                        '/manager/process-templates', '/admin/dashboard', '/admin/api/status', '/scheduler/',
                        '/factory/simulate?order_id=DEMO-BLACK-001', '/factory/api/floor_status/DEMO-WHITE-003'):
                self.assertEqual(browser.get(url).status_code, 200, url)
            self.assertIn('離線協作模式', browser.get('/').get_data(as_text=True))
            comparison = browser.get('/scheduler/api/compare_algorithms')
            self.assertEqual(comparison.status_code, 200, comparison.json)
            self.assertEqual(len(comparison.json['comparison']), 4)
            detail = browser.get('/manager/orders/' + order_id)
            self.assertEqual(detail.status_code, 200)
            with browser.session_transaction() as session:
                csrf = session['mes_csrf']  # Offline UI correctly omits the dispatch form.
            browser.post('/manager/orders/' + order_id + '/send-to-mes', data={'csrf_token': csrf, 'wp_no': '5000'})
            with app.app_context(), closing(db.get_order_mgmt_db()) as orders:
                self.assertIsNone(orders.execute('SELECT mes_request FROM order_list WHERE order_id=?', (order_id,)).fetchone()[0])
            # Advance only the local simulation clock; no waiting or MES/PLC requests.
            now = datetime.now()
            for step in range(30):
                with patch.object(factory_routes, '_now', return_value=now + timedelta(seconds=step * 10)):
                    factory_routes._tick_all_active_orders(app)
            snapshot = browser.get('/factory/api/floor_status/' + order_id).json
            self.assertEqual(snapshot['status'], 'completed')
            self.assertTrue(all(piece['state'] == 'finished' for piece in snapshot['pieces']))
            self.assertEqual(browser.get('/factory/api/floor_cloud_status').status_code, 503)
            self.assertTrue(browser.post('/admin/api/restock').json['success'])
        self.assertEqual(originals, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals})


if __name__ == '__main__':
    unittest.main()
