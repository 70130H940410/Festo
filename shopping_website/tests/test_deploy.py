"""Hosted mode separation, restart persistence, and request authorization."""
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.test import Client
from werkzeug.wrappers import Response
from dev import init_demo, DEMO_PASSWORD
from deploy import build_site
from export_web_databases import export_databases


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = {'FESTO_STORAGE_DIR': str(self.root), 'FESTO_SECRET_KEY': 'test-only-secret-' * 3,
                         'FESTO_COOKIE_SECURE': '0'}

    def post(self, client, url, **kwargs):
        mode = url.split('/')[1]
        return client.post(url, headers={'Origin': 'http://localhost',
                                        'Referer': 'http://localhost/' + mode + '/'}, **kwargs)

    def test_restart_reuses_data_and_unconfigured_online_stays_closed(self):
        site, apps = build_site(self.settings)
        browser = Client(site, Response)
        self.assertEqual(browser.get('/').status_code, 200)
        self.assertEqual(browser.get('/healthz').json, {'status': 'ok'})
        self.assertEqual(browser.get('/online/').status_code, 503)
        with closing(sqlite3.connect(self.root/'offline/product.db')) as db:
            db.execute('UPDATE products SET stock=17 WHERE id=1')
            db.commit()
        build_site(self.settings)
        with closing(sqlite3.connect(self.root/'offline/product.db')) as db:
            self.assertEqual(db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0],17)
        response = self.post(browser, '/offline/login', data={'user_login': 'demo_admin','password': DEMO_PASSWORD})
        self.assertEqual(response.location, '/offline/order')
        self.assertIn('Path=/offline', response.headers['Set-Cookie'])
        page = browser.get('/offline/factory/simulate?order_id=DEMO-BLACK-001').get_data(as_text=True)
        self.assertIn('window.festoUrl = path => "/offline" + path', page)
        self.assertIn('/offline/static/js/factory-floor.js', page)

    def test_invalid_configuration_does_not_initialize_anything(self):
        for extra in ({'FESTO_SECRET_KEY': ''}, {'FESTO_ONLINE_ENABLED': '1'},
                      {'FESTO_ONLINE_ENABLED': '1','SUPABASE_URL': 'https://example.invalid','SUPABASE_KEY': 'test-only'}):
            with self.assertRaises((ValueError, sqlite3.OperationalError)):
                build_site(dict(self.settings, **extra))
            self.assertFalse((self.root/'offline').exists())

    def test_private_export_preserves_source_and_refuses_overwrite(self):
        source = self.root/'source'
        init_demo(source)
        with self.assertRaises(ValueError):
            export_databases(source, self.root/'rejected')
        (source/'.festo-demo').unlink()  # Test fixture only.
        before = {p.name:p.read_bytes() for p in source.glob('*.db')}
        dest = export_databases(source, self.root/'export')
        self.assertEqual(before, {p.name:p.read_bytes() for p in source.glob('*.db')})
        with self.assertRaises(FileExistsError):
            export_databases(source, dest)
        with closing(sqlite3.connect(dest/'order_management.db')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM order_list').fetchone()[0],3)

    def test_both_modes_isolate_sessions_databases_and_connections(self):
        live = self.root/'online'
        init_demo(live)  # Synthetic test fixture only; never uploaded or used as a live DB.
        enabled = dict(self.settings, FESTO_ONLINE_ENABLED='1', SUPABASE_URL='https://example.invalid', SUPABASE_KEY='test-only')
        with self.assertRaises(ValueError):
            build_site(enabled)
        (live/'.festo-demo').unlink()
        with closing(sqlite3.connect(live/'User_Data.db')) as db:
            db.execute("UPDATE User_profile SET account='fixture_' || account")
            db.commit()
        with patch('socket.socket.connect', side_effect=AssertionError('No network allowed in unit tests')):
            site, apps = build_site(enabled)
            from core import db
            from core.sse import get_sse_manager
            from core.mes_data_service import _get_cached, _set_cached
            with apps['online'].app_context():
                live_notifications = get_sse_manager().listen()
                _set_cached('mode-test', 'live-only')
            with apps['offline'].app_context():
                self.assertIsNone(_get_cached('mode-test'))
                get_sse_manager().announce('demo-only')
            self.assertTrue(live_notifications.empty())
            cached = object()
            with patch.object(db, '_supabase_client', cached), patch.dict(os.environ, {'FESTO_OFFLINE': '1'}):
                with apps['offline'].app_context():
                    self.assertIsNone(db.get_supabase_client())
                    self.assertEqual(Path(db.database_path('product.db')), self.root/'offline/product.db')
                with apps['online'].app_context():
                    self.assertIs(db.get_supabase_client(), cached)
                    self.assertEqual(Path(db.database_path('product.db')), live/'product.db')
                    with self.assertRaises(RuntimeError):
                        db.get_festo_db()
            browser = Client(site, Response)
            self.post(browser, '/offline/login', data={'user_login':'demo_admin','password':DEMO_PASSWORD})
            self.assertEqual(browser.get('/online/admin/dashboard').location, '/online/login')
            response = self.post(browser, '/online/login', data={'user_login':'fixture_demo_admin','password':DEMO_PASSWORD})
            self.assertIn('festo_online=', response.headers['Set-Cookie'])
            self.assertIn('Path=/online', response.headers['Set-Cookie'])
            self.assertTrue(self.post(browser, '/offline/admin/api/restock').json['success'])
            with closing(sqlite3.connect(live/'product.db')) as conn:
                self.assertEqual(conn.execute('SELECT stock FROM raw_materials WHERE id=1').fetchone()[0],200)
            browser.get('/offline/logout')
            self.assertEqual(browser.get('/offline/admin/dashboard').location, '/offline/login')
            self.assertEqual(browser.get('/online/admin/dashboard').status_code,200)

    def test_deployment_blocks_anonymous_admin_and_cross_origin_writes(self):
        site, apps = build_site(self.settings)
        browser = Client(site, Response)
        self.assertEqual(self.post(browser,'/offline/admin/api/restock').status_code,302)
        self.post(browser,'/offline/login',data={'user_login':'demo_customer','password':DEMO_PASSWORD})
        self.assertEqual(self.post(browser,'/offline/admin/api/restock').status_code,403)
        self.assertEqual(browser.post('/offline/login',headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(browser.post('/offline/login',headers={'Origin':'http://localhost','Referer':'http://localhost/online/'}).status_code,403)
        self.assertEqual(browser.get('/offline/debug_db').status_code,404)
        self.assertEqual(browser.get('/offline/factory/api/reset/DEMO-BLACK-001').status_code,404)


if __name__ == '__main__':
    unittest.main()
