"""Copy the working runtime onto the factory PC without changing either old version."""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import os
import shutil
import encodings
import pyodbc
import sqlite3
import subprocess
import sys


PROBE = r'''
from pathlib import Path
import sys, json, ssl, sqlite3, pyodbc, supabase
from importlib.metadata import version
root = Path(sys.executable).resolve().parent
assert Path(sys.base_prefix).resolve() == root
assert Path(sys.prefix).resolve() == root
for path in sys.path:
    if path:
        assert Path(path).resolve().is_relative_to(root), path
for module in tuple(sys.modules.values()):
    path = getattr(module, '__file__', None)
    if path and not path.startswith('<'):
        assert Path(path).resolve().is_relative_to(root), path
connection = pyodbc.connect(r'Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=C:\MES4\FestoMES.accdb;', readonly=True, autocommit=True)
row = connection.cursor().execute('SELECT ONo, [End], State FROM tblFinOrder WHERE ONo=3555').fetchone()
assert row and row[1] is not None, 'Live MES completion not found'
connection.close()
print(json.dumps(dict(python=sys.executable, prefix=sys.prefix, version=sys.version, paths=sys.path, pyodbc=version('pyodbc'), supabase=version('supabase'), mes_3555=list(map(str,row)))))
'''


def install():
    source = Path.home() / 'FestoSync_CompletionCopy'
    target = Path.home() / 'FestoSync_Standalone'
    assert source.is_dir() and not target.exists(), 'Source missing or destination exists; inspect first'
    base = Path(encodings.__file__).resolve().parents[2]
    packages = Path(pyodbc.__file__).resolve().parent
    print('[RUNTIME SOURCES]', 'configured:',sys.base_prefix,'actual:',base,'packages:',packages,flush=True)
    assert (base / 'python.exe').exists() and (base / 'Lib').is_dir() and packages.is_dir()
    assert not list(base.glob('*._pth')), 'Embedded Python configuration requires review'
    old_app = source / 'shopping_website'
    original_files = [source / 'StartSync_CompletionCopy.vbs'] + [old_app / name for name in ('sync_agent_completion.py','mes_completion.py','mes_dispatch.py')]
    checksum = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    original_hashes = {str(p):checksum(p) for p in original_files}
    launcher = original_files[0].read_bytes().decode('utf-16')
    old_venv = 'venvDir    = "H:\\Festo_Cloud_Update\\shopping_website\\venv"'
    old_exe = 'pythonExe  = venvDir & "\\Scripts\\python.exe"'
    assert launcher.count(old_venv) == launcher.count(old_exe) == 1
    entries = [(base / 'Lib', True), (base / 'DLLs', False), (packages, False)]
    size = sum(p.stat().st_size for folder,exclude_packages in entries if folder.exists() for p in folder.rglob('*') if p.is_file() and not (exclude_packages and 'site-packages' in p.relative_to(folder).parts))
    assert shutil.disk_usage(target.parent).free > size * 1.2 + 100_000_000, 'Insufficient free space'
    print('[SOURCE]', sys.executable, flush=True)
    print('[BASE]', base, flush=True)
    print('[COPY]', round(size / 1024**2), 'MiB; originals remain untouched', flush=True)
    runtime = target / 'Python'
    runtime.mkdir(parents=True)
    shutil.copytree(base / 'Lib', runtime / 'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__'))
    if (base / 'DLLs').exists():
        shutil.copytree(base / 'DLLs', runtime / 'DLLs')
    for pattern in ('python*.exe','*.dll','python*.zip','LICENSE*'):
        for path in base.glob(pattern):
            if path.is_file(): shutil.copy2(path, runtime / path.name)
    shutil.copytree(packages, runtime / 'Lib/site-packages', ignore=shutil.ignore_patterns('__pycache__'))
    clean_env = {k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV')}
    clean_env['PATH'] = str(runtime) + os.pathsep + str(Path(os.environ['SystemRoot']) / 'System32') + os.pathsep + os.environ['SystemRoot']
    print('[VERIFY] Isolated local Python, packages and read-only MES access', flush=True)
    result = subprocess.run([str(runtime / 'python.exe'), '-I', '-c', PROBE], cwd=runtime, env=clean_env, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    from importlib.metadata import version
    assert report['pyodbc'] == version('pyodbc') and report['supabase'] == version('supabase')
    app = target / 'shopping_website'
    app.mkdir()
    for path in original_files[1:]: shutil.copy2(path, app / path.name)
    journal = old_app / 'mes_dispatch_receipts_completion.db'
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True)) as db:
        receipts = db.execute('SELECT * FROM receipts ORDER BY cloud_id,line_no').fetchall()
        assert not any(r[0] for r in db.execute("SELECT 1 FROM receipts WHERE state IN ('sending','retry_authorized')")), 'Dispatch in flight; stop and inspect'
        owner = db.execute('SELECT * FROM agent').fetchall()
        with closing(sqlite3.connect(app / journal.name)) as dest:
            db.backup(dest)
            assert receipts == dest.execute('SELECT * FROM receipts ORDER BY cloud_id,line_no').fetchall()
            assert owner == dest.execute('SELECT * FROM agent').fetchall()
    launcher = launcher.replace(old_venv, 'venvDir    = scriptDir & "\\Python"').replace(old_exe, 'pythonExe  = venvDir & "\\python.exe"')
    assert 'H:\\' not in launcher and '\r\r\n' not in launcher
    (target / 'StartSync_Standalone.vbs').write_bytes(launcher.encode('utf-16'))
    assert all(checksum(Path(p)) == digest for p,digest in original_hashes.items())
    report['originals_preserved'] = original_hashes
    report['receipt_count'] = len(receipts)
    (target / 'runtime_verified.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('[OK]', result.stdout.strip(), flush=True)
    print('[OK] Existing programs and receipt identity preserved.', flush=True)
    print('[START ONLY]', target / 'StartSync_Standalone.vbs', flush=True)
    print('[NOTE] Do not run the USB or CompletionCopy launcher at the same time.', flush=True)
    os.startfile(target)


if __name__ == '__main__':
    try:
        install()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr)
        raise
