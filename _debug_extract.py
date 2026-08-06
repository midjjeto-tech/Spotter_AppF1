import hashlib
import os
from PyInstaller.archive.readers import CArchiveReader

r = CArchiveReader(r'dist\SpotterApp.exe')
names = [
    'torch\\lib\\torch_global_deps.dll',
    'torch\\lib\\torch_python.dll',
    'torch\\lib\\uv.dll',
    'torch\\lib\\c10.dll',
]
for n in names:
    data = r.extract(n)
    h = hashlib.sha256(data).hexdigest()
    print(n, 'len=', len(data), 'sha256=', h[:16], 'PE header ok=', data[:2] == b'MZ')

print('--- originals in venv ---')
base = r'.venv\Lib\site-packages\torch\lib'
for n in ['torch_global_deps.dll', 'torch_python.dll', 'uv.dll', 'c10.dll']:
    p = os.path.join(base, n)
    data = open(p, 'rb').read()
    h = hashlib.sha256(data).hexdigest()
    print(n, 'len=', len(data), 'sha256=', h[:16])
