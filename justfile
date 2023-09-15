export PATH := env_var("PATH") + ":" + env_var("HOME") + "/.local/bin"

help:
  just --list

prepare:
  #!/bin/bash
  if ! &>/dev/null which poetry; then
    curl -sSL https://install.python-poetry.org | sed -e 's|symlinks=False|symlinks=True|' | python3 -
  fi

  if ! &>/dev/null poetry env list; then
    poetry install
  fi

  # check for presence of the extism shared library and headers, installing
  # then if necessary
  if ! &>/dev/null poetry run python3 -m extism.utils; then
    if ! &>/dev/null which extism; then
      pip3 install git+https://github.com/extism/cli
    fi

    extism install git
  fi

test: prepare
  poetry run python -m unittest discover

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
