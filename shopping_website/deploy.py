"""One host, isolated /offline and /online applications; one background worker each."""
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import threading
from urllib.parse import urlsplit

# Hosted configuration must come from the host, never a developer's .env.
os.environ['FESTO_SKIP_DOTENV'] = '1'

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from app import create_app, background_factory_worker
from dev import init_demo, validate_demo


def validate_online(directory):
    """Read only. A missing live database must never become an empty SQLite file."""
    if (directory / '.festo-demo').exists():
        raise ValueError('Online mode cannot use a demo database.')
    required = {'User_Data.db': 'User_profile', 'product.db': 'standard_process',
                'order_management.db': 'order_list'}
    for filename, table in required.items():
        with closing(sqlite3.connect((directory / filename).as_uri() + '?mode=ro', uri=True)) as db:
            db.execute(f'SELECT * FROM {table} LIMIT 0')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Online database integrity check failed: ' + filename)
            if filename == 'User_Data.db' and db.execute(
                    "SELECT 1 FROM User_profile WHERE account IN ('demo_admin','demo_customer') LIMIT 1").fetchone():
                raise ValueError('Public demo accounts are not allowed in online mode.')


def protect_hosted_app(app, mode):
    @app.before_request
    def access():
        if request.endpoint == 'static':
            return
        # Disable development GET mutations and public manager registration on the host.
        if request.path == '/debug_db' or (mode == 'online' and request.path == '/register/manager') or request.path.startswith(
                ('/factory/api/init/', '/factory/api/reset/', '/factory/api/tick', '/factory/api/debug/')):
            abort(404)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin') or request.headers.get('Referer', '')
            source = urlsplit(origin)
            if not source.scheme or source.netloc != request.host:
                abort(403)
            # Tabs in different modes must not post to one another, even on the same host.
            if request.headers.get('Referer') and not urlsplit(request.headers['Referer']).path.startswith('/' + mode + '/'):
                abort(403)
        public = request.path in ('/', '/login', '/register/customer')
        if not public and not session.get('user_id'):
            return redirect(url_for('auth.login'))
        if request.blueprint in ('admin', 'manager') and session.get('role') != 'admin':
            abort(403)
        if mode == 'online' and request.blueprint in ('factory', 'scheduler') and session.get('role') != 'admin':
            abort(403)
        if mode == 'online' and request.path == '/factory/api/trigger_mes_error':
            abort(403)  # Hosted website does not directly alter physical machine error flags.


def build_site(settings=None):
    settings = dict(os.environ if settings is None else settings)
    secret = settings.get('FESTO_SECRET_KEY', '')
    if len(secret) < 32:
        raise ValueError('Set FESTO_SECRET_KEY to a persistent random value of at least 32 characters.')
    root = Path(settings.get('FESTO_STORAGE_DIR', '')).expanduser()
    if not root.is_absolute():
        raise ValueError('FESTO_STORAGE_DIR must be an absolute persistent storage path.')
    root = root.resolve()
    if root == (Path(__file__).parent / 'database').resolve():
        raise ValueError('Use separate deployment storage, not the original database directory.')
    demo_dir, online_dir = root / 'offline', root / 'online'
    enabled = settings.get('FESTO_ONLINE_ENABLED') == '1'
    if enabled:
        if not settings.get('SUPABASE_URL') or not settings.get('SUPABASE_KEY'):
            raise ValueError('Online mode requires SUPABASE_URL and SUPABASE_KEY.')
        validate_online(online_dir)
    if not demo_dir.exists():
        init_demo(demo_dir)
    validate_demo(demo_dir)
    applications = {}
    for mode, directory in [('offline', demo_dir)] + ([('online', online_dir)] if enabled else []):
        app = create_app({'DATABASE_DIR': str(directory), 'OFFLINE_MODE': mode == 'offline',
                          'CLOUD_ONLY': mode == 'online', 'DUAL_MODE': True,
                          'SECRET_KEY': secret + ':' + mode,
                          'SESSION_COOKIE_NAME': 'festo_' + mode,
                          'SESSION_COOKIE_PATH': '/' + mode,
                          'SESSION_COOKIE_SECURE': settings.get('FESTO_COOKIE_SECURE', '1') != '0',
                          'SESSION_COOKIE_HTTPONLY': True, 'SESSION_COOKIE_SAMESITE': 'Lax'})
        protect_hosted_app(app, mode)
        applications[mode] = app
    portal = Flask('festo_portal', template_folder=str(Path(__file__).parent / 'templates'), static_folder=None)

    @portal.get('/')
    def home():
        return render_template('portal.html', online_enabled=enabled)

    @portal.get('/healthz')
    def health():
        return {'status': 'ok'}

    @portal.get('/online/')
    def unavailable():
        return render_template('portal.html', online_enabled=False), 503

    mounts = {'/' + mode: app for mode, app in applications.items()}
    return DispatcherMiddleware(portal, mounts), applications


def main():
    from waitress import serve
    site, applications = build_site()
    for app in applications.values():
        threading.Thread(target=background_factory_worker, args=(app,), daemon=True).start()
    serve(site, host='0.0.0.0', port=int(os.environ.get('PORT', '8768')), threads=32)


if __name__ == '__main__':
    main()
