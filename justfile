export PATH := env_var("PATH") + ":" + env_var_or_default("HOME", env_var_or_default("APPDATA", "")) + "/.local/bin"

# Make just arguments available as env vars; useful for preserving
# quotes.
set export

_help:
  @just --list

prepare:
  #!/bin/bash
  if ! &>/dev/null which poetry; then
    curl -sSL https://install.python-poetry.org | sed -e 's|symlinks=False|symlinks=True|' | python3 -
  fi

  envs="$(poetry env list || true)"
  if [ ! $? ] || [ -z "$envs" ]; then
    poetry install --no-cache
  fi

test: prepare
  #!/bin/bash
  set -eou pipefail
  poetry run python -m unittest discover

  set +e
  msg=$(2>&1 poetry run python example.py)
  if [ $? != 0 ]; then
    >&2 echo "$msg"
    exit 1
  else
    echo -e 'poetry run python example.py... \x1b[32mok\x1b[0m'
  fi

poetry *args: prepare
  #!/bin/bash
  poetry $args

clean:
  rm -rf dist/*

build: clean prepare
  poetry build

publish: clean prepare
  poetry build
  poetry run twine upload dist/extism-*.tar.gz

format: prepare
  poetry run black extism/ tests/ example.py

lint: prepare
  poetry run mypy --check extism/ tests/ example.py
  poetry run black --check extism/ tests/ example.py

docs: prepare
  poetry run sphinx-build -b html docs/source docs/_build

serve-docs: docs
  poetry run python -m http.server 8000 -d docs/_build

watch-docs: prepare
  watchexec -r -w docs/source -w extism just serve-docs

show-docs: docs
  open docs/extism.html
