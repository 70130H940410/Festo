"""Create and run an isolated offline demo; never open an existing production DB."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading

ROOT = Path(__file__).resolve().parent
DATABASES = {'User_Data.db': 'users.sql', 'product.db': 'products.sql',
             'order_management.db': 'orders.sql'}
DEMO_PASSWORD = 'LocalDemo123!'
SCHEMA_VERSION = 1


def init_demo(directory):
    directory = Path(directory).resolve()
    # mkdir is exclusive: no --force, no overwriting, even for an empty existing directory.
    directory.mkdir(parents=True, exist_ok=False)
    from werkzeug.security import generate_password_hash
    for name, schema in DATABASES.items():
        with closing(sqlite3.connect(directory / name)) as db:
            db.executescript((ROOT / 'database/schema' / schema).read_text(encoding='utf-8'))
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('ATTACH DATABASE ? AS products', (str(directory / 'product.db'),))
        db.execute('ATTACH DATABASE ? AS orders', (str(directory / 'order_management.db'),))
        db.executescript((ROOT / 'database/seed_demo.sql').read_text(encoding='utf-8'))
    with closing(sqlite3.connect(directory / 'User_Data.db')) as db:
        db.execute('INSERT INTO registration_key VALUES (?,?)', ('Demo Factory', 'LOCAL-DEMO-ONLY'))
        for account, role in (('demo_admin', 'admin'), ('demo_customer', 'customer')):
            db.execute('INSERT INTO User_profile VALUES (?,?,?,?,?,?,?)',
                       (account, account, account + '@example.invalid',
                        generate_password_hash(DEMO_PASSWORD), role,
                        'LOCAL-DEMO-ONLY' if role == 'admin' else None, '協作測試帳號'))
        db.commit()
    # Written last: a failed/partial initialization cannot be launched as a demo.
    (directory / '.festo-demo').write_text(json.dumps({'schema_version': SCHEMA_VERSION}), encoding='utf-8')
    validate_demo(directory)
    return directory


def validate_demo(directory):
    directory = Path(directory).resolve()
    marker = directory / '.festo-demo'
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Not an initialized demo directory. Run dev.py init with a NEW directory first.')
    for name in DATABASES:
        # mode=ro also prevents accidentally creating empty databases during validation.
        with closing(sqlite3.connect((directory / name).as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError('Unsupported demo schema version: ' + name)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed: ' + name)
    return directory


def create_demo_app(directory):
    directory = validate_demo(directory)
    # Set before importing the website so an existing .env cannot enable live connections.
    os.environ['FESTO_OFFLINE'] = '1'
    os.environ['FESTO_DATA_DIR'] = str(directory)
    from app import create_app
    return create_app({'DATABASE_DIR': str(directory), 'OFFLINE_MODE': True,
                       'SECRET_KEY': secrets.token_hex(32)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'run', 'check'))
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local-data')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            directory = init_demo(args.data_dir)
            print('Created synthetic demo databases:', directory)
            print('Accounts: demo_admin / demo_customer; password:', DEMO_PASSWORD)
            print('Offline development only. No existing databases were read or changed.')
        elif args.command == 'check':
            print('Demo databases OK:', validate_demo(args.data_dir))
        else:
            app = create_demo_app(args.data_dir)
            from app import background_factory_worker
            threading.Thread(target=background_factory_worker, args=(app,), daemon=True).start()
            print('OFFLINE DEMO: no Supabase, no Access, no factory dispatch.')
            print('Data directory:', app.config['DATABASE_DIR'])
            app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\nExisting data is never overwritten. Choose a new --data-dir for a fresh demo.\n')


if __name__ == '__main__':
    main()
