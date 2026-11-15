from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_agent import sync_finished_steps, factory_timestamp


class FinishedStepsTest(unittest.TestCase):
    def setUp(self):
        self.sb, self.cur, self.state = Mock(), Mock(), {}
        self.start = datetime(2026, 11, 11, 12)

    def row(self, minute, step=10, description='measure'):
        return (1211, step, 3510, description, 6, None, None,
                self.start, self.start + timedelta(minutes=minute))

    def batch(self):
        return self.sb.table.return_value.upsert.call_args.args[0]

    def test_duplicate_keys_select_latest_independent_of_input_order(self):
        rows = [self.row(5), self.row(1), self.row(3, step=20), self.row(5)]
        self.cur.fetchall.return_value = rows
        sync_finished_steps(self.sb, self.cur, self.state)
        self.assertEqual(len(self.batch()), 2)
        self.assertEqual(self.state['finstep_snapshots'][(3510, 10)]['end'], factory_timestamp(self.row(5)[8]))
        self.cur.fetchall.return_value = list(reversed(rows))
        sync_finished_steps(self.sb, self.cur, self.state)
        self.assertEqual(self.sb.table.return_value.upsert.call_count, 1)

    def test_failed_upload_is_retried_without_advancing_snapshot(self):
        self.cur.fetchall.return_value = [self.row(1)]
        sync_finished_steps(self.sb, self.cur, self.state)
        self.cur.fetchall.return_value = [self.row(1), self.row(5)]
        self.sb.table.return_value.upsert.return_value.execute.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            sync_finished_steps(self.sb, self.cur, self.state)
        self.assertEqual(self.state['finstep_snapshots'][(3510, 10)]['end'], factory_timestamp(self.row(1)[8]))
        self.sb.table.return_value.upsert.return_value.execute.side_effect = None
        sync_finished_steps(self.sb, self.cur, self.state)
        self.assertEqual(self.state['finstep_snapshots'][(3510, 10)]['end'], factory_timestamp(self.row(5)[8]))

    def test_metadata_correction_and_null_dates(self):
        row = list(self.row(1)); row[7] = row[8] = None
        self.cur.fetchall.return_value = [tuple(row)]
        sync_finished_steps(self.sb, self.cur, self.state)
        self.assertIsNone(self.batch()[0]['end'])
        row[3] = 'corrected'
        self.cur.fetchall.return_value = [tuple(row)]
        sync_finished_steps(self.sb, self.cur, self.state)
        self.assertEqual(self.batch()[0]['description'], 'corrected')
        self.assertEqual(self.sb.table.return_value.upsert.call_count, 2)


if __name__ == '__main__':
    unittest.main()
