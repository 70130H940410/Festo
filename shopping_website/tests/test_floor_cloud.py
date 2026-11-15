"""Read-only MES projection and endpoint authorization; no production writes."""
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from core import factory_routes
from core.floor_cloud import floor_cloud_snapshot


class Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters = client, table, {}

    def select(self, value):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, count):
        return self

    def execute(self):
        self.client.calls.append((self.table, self.filters))
        if self.table == self.client.fail:
            raise RuntimeError('offline')
        rows = self.client.data[self.table]
        return SimpleNamespace(data=[r for r in rows if all(r.get(k) == v for k, v in self.filters.items())])


class Client:
    def __init__(self):
        self.calls, self.fail = [], None
        self.data = {
            'tbl_resource': [{'resource_id': 7, 'resource_name': 'Drill'}],
            'tbl_machine_report': [{'resource_id': 7, 'timestamp': '2020-01-01T00:00:00Z',
                                    'busy': True, 'error_l1': True}],
            'tbl_order': [{'ono': 42, 'state': 1, 'start': None, 'end': None}, {'ono': 43}],
            'tbl_fin_step': [{'ono': 42, 'step_no': 30, 'resource_id': 7}, {'ono': 43, 'step_no': 40}],
        }

    def table(self, name):
        return Query(self, name)


class CloudTests(unittest.TestCase):
    def test_existing_tables_and_exact_order_mapping(self):
        client = Client()
        data = floor_cloud_snapshot(client, 'local-order', 42)
        self.assertEqual(data['order']['ono'], 42)
        self.assertEqual(len(data['steps']), 1)
        self.assertEqual(data['steps'][0]['ono'], 42)
        self.assertFalse(data['piece_tracking_available'])
        self.assertFalse(data['robot_tracking_available'])
        self.assertEqual(data['machines'][0]['freshness'], 'old')
        self.assertTrue(data['machines'][0]['ErrorL1'])

    def test_unmapped_order_never_invents_progress(self):
        client = Client()
        data = floor_cloud_snapshot(client, 'unmapped')
        self.assertEqual(data['steps'], [])
        self.assertIsNone(data['order'])
        self.assertFalse(any(t == 'tbl_fin_step' for t, _ in client.calls))

    def test_partial_failure_does_not_retain_steps(self):
        client = Client()
        client.fail = 'tbl_fin_step'
        data = floor_cloud_snapshot(client, 'local-order', 42)
        self.assertEqual(data['connection'], 'degraded')
        self.assertEqual(data['steps'], [])
        self.assertIsNotNone(data['steps_error'])
        self.assertTrue(data['machines'])

    def test_endpoint_permissions_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orders.db'
            db = sqlite3.connect(path)
            db.executescript("CREATE TABLE order_list(order_id TEXT,mes_ono INT,status TEXT); INSERT INTO order_list VALUES('test',42,'active');")
            db.close()
            before = path.read_bytes()
            fake = Client()
            with patch.object(factory_routes, '_db_path', return_value=str(path)), patch('core.db.get_supabase_client', return_value=fake) as getter:
                with create_app().test_client() as browser:
                    self.assertNotEqual(browser.get('/factory/api/floor_cloud_status').status_code, 200)
                    with browser.session_transaction() as session:
                        session['user_id'] = 1
                        session['role'] = 'user'
                    self.assertEqual(browser.get('/factory/api/floor_cloud_status').status_code, 403)
                    getter.assert_not_called()
                    with browser.session_transaction() as session:
                        session['role'] = 'admin'
                    response = browser.get('/factory/api/floor_cloud_status?order_id=test')
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['mes_ono'], 42)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertEqual(browser.get('/factory/api/floor_cloud_status?order_id=missing').status_code, 404)
                    fake.fail = 'tbl_machine_report'
                    self.assertEqual(browser.get('/factory/api/floor_cloud_status').status_code, 503)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
