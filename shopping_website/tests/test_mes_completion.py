import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mes_completion import completed_receipts, sync_finished_orders
from sync_agent import factory_timestamp
from core.order_sync import sync_line_orders_to_order_list


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.items = {'mes_dispatch': {'lines': [{'quantity': 1, 'wp_no': 5000}]},
                      'mes_receipts': [{'line_no': 0, 'ono': 3555, 'quantity': 1,
                                        'wp_no': 5000, 'records_verified': True}]}
        start = datetime(2026, 11, 15, 16, 14, 56)
        self.row = (3555, None, None, start, start + timedelta(seconds=62), 2, True, 0)
        self.cur = Mock()
        self.cur.fetchall.return_value = [self.row]
        self.cur.fetchone.return_value = self.row
        self.sb = Mock()
        self.headers, self.cloud = Mock(), Mock()
        self.sb.table.side_effect = lambda name: self.headers if name == 'tbl_order' else self.cloud
        self.raw = json.dumps(self.items)
        self.cloud.select.return_value.like.return_value.execute.return_value.data = [
            {'id': 19, 'status': 'In Production (MES ONo: 3555)', 'items': self.raw}]
        self.cloud.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{'id': 19}]

    def test_archive_carries_real_end_and_completes_existing_order_only(self):
        state = {}
        sync_finished_orders(self.sb, self.cur, state, factory_timestamp)
        self.assertEqual(self.headers.upsert.call_args.args[0][0]['end'], '2026-11-15T08:15:58+00:00')
        self.cloud.update.assert_called_once_with({'status': 'Completed'})
        self.cloud.update.return_value.eq.return_value.eq.return_value.eq.assert_called_with('items', json.dumps(self.raw, ensure_ascii=False))
        self.assertTrue(all('NOT IN (SELECT ONo FROM tblOrder)' in call.args[0] for call in self.cur.execute.call_args_list))

    def test_missing_archive_does_not_complete(self):
        self.cur.fetchone.return_value = None
        sync_finished_orders(self.sb, self.cur, {}, factory_timestamp)
        self.cloud.update.assert_not_called()

    def test_all_receipts_must_finish(self):
        self.items['mes_dispatch']['lines'] *= 2
        self.items['mes_receipts'].append(dict(self.items['mes_receipts'][0], line_no=1, ono=3556))
        self.cloud.select.return_value.like.return_value.execute.return_value.data[0]['items'] = self.items
        self.cur.fetchone.side_effect = [self.row, None]
        sync_finished_orders(self.sb, self.cur, {}, factory_timestamp)
        self.cloud.update.assert_not_called()

    def test_invalid_partial_or_duplicate_receipts_fail_closed(self):
        for key, value in [('records_verified', False), ('quantity', 2), ('wp_no', 1211), ('line_no', 1)]:
            item = copy.deepcopy(self.items)
            item['mes_receipts'][0][key] = value
            self.assertEqual(completed_receipts(item), [])
        self.items['mes_dispatch']['lines'] *= 2
        self.items['mes_receipts'] *= 2
        self.assertEqual(completed_receipts(self.items), [])

    def test_failed_header_upload_retries_and_never_marks_complete(self):
        state = {}
        self.headers.upsert.return_value.execute.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            sync_finished_orders(self.sb, self.cur, state, factory_timestamp)
        self.assertEqual(state['finished_order_snapshots'], {})
        self.cloud.update.assert_not_called()
        self.headers.upsert.return_value.execute.side_effect = None
        sync_finished_orders(self.sb, self.cur, state, factory_timestamp)
        self.assertIn(3555, state['finished_order_snapshots'])

    def test_website_refresh_completes_target_and_preserves_terminal_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orders.db'
            def connect():
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                return db
            db = connect()
            db.executescript("CREATE TABLE order_list(order_id TEXT,supabase_order_id INT,mes_ono INT,status TEXT);"
                             "INSERT INTO order_list VALUES('test',19,3555,'active');"
                             "INSERT INTO order_list VALUES('cancel',20,3556,'cancelled');")
            db.commit(); db.close()
            query = Mock()
            query.select.return_value = query.eq.return_value = query.order.return_value = query
            query.execute.return_value.data = [{'id': 19, 'status': 'Completed', 'client_id': 'web:123', 'items': {}}]
            sb = Mock(); sb.table.return_value = query
            with patch('core.order_sync.get_order_mgmt_db', side_effect=connect), patch('core.order_sync.get_supabase_client', return_value=sb):
                self.assertEqual(sync_line_orders_to_order_list('test'), 1)
                query.eq.assert_called_once_with('id', 19)
                self.assertEqual(sync_line_orders_to_order_list('test'), 0)
                self.assertEqual(sync_line_orders_to_order_list('cancel'), 0)
            db = connect()
            self.assertEqual(tuple(db.execute("SELECT status,mes_ono FROM order_list WHERE order_id='test'").fetchone()), ('completed',3555))
            self.assertEqual(db.execute("SELECT status FROM order_list WHERE order_id='cancel'").fetchone()[0], 'cancelled')
            db.close()


if __name__ == '__main__':
    unittest.main()
