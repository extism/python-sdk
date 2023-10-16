# Extism Python Host SDK

This repo contains the Python package for integrating with the
[Extism](https://extism.org/) Webassembly framework. Install this library into
your Python application host to run Extism WebAssembly guest plug-ins.

> **Note**: :warning: This repo is 1.0 alpha version of the Python SDK and is a work in
> progress. :warning:
>
> We'd love any feedback you have on it, but consider using the supported
> python SDK in
> [extism/extism](https://github.com/extism/extism/tree/main/python) until we
> hit 1.0.

```python
import extism
import json

manifest = {"wasm": [{"url": "https://github.com/extism/plugins/releases/latest/download/count_vowels.wasm"}]}
with extism.Plugin(manifest, wasi=True) as plugin:
    wasm_vowel_count = plugin.call(
        "count_vowels",
        "hello world",
        parse = lambda output: json.loads(bytes(output).decode('utf-8'))
    )
print(wasm_vowel_count) # {'count': 3, 'total': 3, 'vowels': 'aeiouAEIOU'}
```

## Installation

Install this package from [PyPI](https://pypi.org/project/extism/):

```shell
# using pip
$ pip install extism==1.0.0rc0 --pre

# using poetry
$ poetry add extism=^1.0.0rc0 --allow-prereleases
```

The `extism` package should install an appropriate `extism_sys` dependency
containing a prebuilt shared object for your system. We support the following
targets:

- MacOS 11.0+, `arm64`
- MacOS 10.7+, `x86_64`
- Manylinux 2.17+, `aarch64`
- Manylinux 2.17+, `x86_64`
- MUSL Linux 1.2+, `aarch64`
- Windows (MSVC), `x86_64`

If you need support for a different platform or architecture, please [let us know][let-us-know]!

[let-us-know]: https://github.com/extism/extism/issues/new?title=Please+support+extism_sys+on+my+platform&labels=python&body=Hey%21+Could+you+support+%24PLATFORM+and%2For+%24ARCH%3F

## Documentation

Check out the docs:

- [Getting Started](https://extism.readthedocs.org/en/latest/)
- [API docs](https://extism.readthedocs.org/en/latest/)

## Development

### Local dev

Install [just](https://just.systems). Running `just test` should install all
other prerequisites.

### Release workflow

1. Create a semver-formatted git tag (`git tag v1.0.0`).
2. Push that tag to the repository (`git push origin v1.0.0`.)
3. Wait for [the Build workflow to run](https://github.com/extism/python-sdk/actions/workflows/build.yaml).
4. Once the build workflow finishes, go to the [releases](https://github.com/extism/python-sdk/releases) page. You should
   see a draft release.
5. Edit the draft release. Publish the release.
6. Wait for [the Release workflow to run](https://github.com/extism/python-sdk/actions/workflows/release.yaml).
7. Once the release workflow completes, you should be able to `pip install extism==${YOUR_TAG}` from PyPI.

## LICENSE

[BSD-3-Clause](./LICENSE)
