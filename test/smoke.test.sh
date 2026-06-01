#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"

echo "1. import + pure-function check"
python3 -c "import sys; sys.path.insert(0, '$here/scripts'); import wp_index; \
assert wp_index.slugify('Hello World') == 'hello-world'; \
assert wp_index.html_to_markdown('<p>a <strong>b</strong></p>') == 'a **b**'; \
print('  ok')"

echo "2. --help exits 0"
python3 "$here/scripts/wp_index.py" --help >/dev/null
echo "  ok"

echo "3. unittest suite"
python3 -m unittest discover -s "$here/test" -p "test_*.py"

echo "ALL SMOKE CHECKS PASSED"
