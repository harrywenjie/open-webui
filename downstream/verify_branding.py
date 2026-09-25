"""Check the exact Data Rift family in sources, a wheel, an installed package or HTTP."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent

def verify(read, prefix, manifest):
    checked = 0
    for name, expected in manifest['assets'].items():
        data = read(prefix + 'static/' + name)
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('branding mismatch: ' + prefix + 'static/' + name)
        checked += 1
    data = read(prefix + 'favicon.png')
    if hashlib.sha256(data).hexdigest() != manifest['assets']['favicon.png']['sha256']:
        raise ValueError('branding mismatch: root favicon.png')
    return checked + 1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--wheel', type=Path)
    group.add_argument('--installed', type=Path, help='installed open_webui package directory')
    group.add_argument('--url')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'downstream/branding/manifest.json').read_text())
    if args.wheel:
        with zipfile.ZipFile(args.wheel) as archive:
            count = verify(archive.read, 'open_webui/frontend/', manifest)
    elif args.installed:
        count = verify(lambda name: (args.installed / 'frontend' / name).read_bytes(), '', manifest)
        for name, expected in manifest['assets'].items():
            if hashlib.sha256((args.installed / 'static' / name).read_bytes()).hexdigest() != expected['sha256']:
                raise ValueError('startup runtime branding mismatch: ' + name)
            count += 1
    elif args.url:
        def read(name):
            request = Request(args.url.rstrip('/') + '/' + name, headers={'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=15) as response:
                return response.read()
        count = verify(read, '', manifest)
    else:
        count = verify(lambda name: (ROOT / 'static' / name).read_bytes(), '', manifest)
    print(json.dumps({'result': 'PASS', 'branding_id': manifest['branding_id'], 'checked': count}))

if __name__ == '__main__':
    main()
