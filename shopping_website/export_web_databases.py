"""Export private website SQLite copies, without changing or uploading the source."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3

NAMES = ('User_Data.db', 'product.db', 'order_management.db')


def export_databases(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if (source / '.festo-demo').exists():
        raise ValueError('Do not export demo data as an online factory database.')
    if any(not (source / name).is_file() for name in NAMES):
        raise ValueError('Source must contain all three website databases.')
    destination.mkdir(parents=True, exist_ok=False)
    for name in NAMES:
        with closing(sqlite3.connect((source/name).as_uri()+'?mode=ro', uri=True)) as src, \
             closing(sqlite3.connect(destination/name)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Export failed integrity check: ' + name)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print('Private copies created:', export_databases(args.source, args.destination))
    print('Contains private account/order data. Do not commit or publicly share this directory.')
