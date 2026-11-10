"""Check statically named native operations against the running backend OpenAPI.

Dynamic UUID paths still require contract/device tests; this check deliberately
does not report them as covered merely because their prefix exists.
"""
import argparse
import json
from pathlib import Path
import re
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--openapi', default='http://127.0.0.1:8000/openapi.json')
    args = parser.parse_args()
    with urllib.request.urlopen(args.openapi, timeout=15) as response:
        paths = json.load(response)['paths']
    root = Path(__file__).resolve().parents[1] / 'NxtRepNative'
    pattern = re.compile(r'\.(api|allPages)\("([^"\\]+)"\s*(?:,\s*method:\s*"(GET|POST|PUT|PATCH|DELETE)")?\s*[,)]')
    operations = set()
    failures = []
    for file in root.glob('*.swift'):
        source = file.read_text(encoding='utf-8')
        for match in pattern.finditer(source):
            method = match[3] or 'GET'
            path = '/api/v1/' + match[2]
            operations.add((method, path))
            if method.lower() not in paths.get(path, {}):
                line = source.count('\n', 0, match.start()) + 1
                failures.append(f'{file.name}:{line} {method} {path}')
    if failures:
        raise SystemExit('Native operations missing from OpenAPI:\n'+'\n'.join(failures))
    print(f'PASS: {len(operations)} statically named native operations match live OpenAPI routes and methods')


if __name__ == '__main__':
    main()
