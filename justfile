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
  poetry run python -m unittest discover

poetry *args: prepare
  #!/bin/bash
  poetry $args

clean:
  rm -rf dist/*

publish: clean prepare
  poetry build
  poetry run twine upload dist/extism-*.tar.gz

format: prepare
  poetry run black extism/ tests/ example.py

lint: prepare
  poetry run black --check extism/ tests/ example.py

docs: prepare
  poetry run pycco extism/*.py

show-docs: docs
  open docs/extism.html
