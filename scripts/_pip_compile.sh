#!/usr/bin/env bash
set -euo pipefail
set -x

pip-compile \
  --upgrade \
  --strip-extras \
  --no-emit-index-url \
  --no-emit-trusted-host \
  --output-file=requirements.txt \
  requirements.in

pip-compile \
  --upgrade \
  --strip-extras \
  --no-emit-index-url \
  --no-emit-trusted-host \
  --output-file=requirements-dev.txt \
  requirements-dev.in

sed -i 's/\r$//' requirements.txt requirements-dev.txt
for f in requirements.txt requirements-dev.txt; do
  sed -i -E '/^#    pip-compile/ s/ --[a-z-]+=None//g' "$f"
done
echo "==> lock-файлы обновлены"
