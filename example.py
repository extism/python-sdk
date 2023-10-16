# run this using `poetry run python example.py`!
import sys

import json
import hashlib
import pathlib

from extism import Function, host_fn, ValType, Plugin, set_log_file, Json
from typing import Annotated

set_log_file("stderr", "trace")


@host_fn(user_data=b"Hello again!")
def hello_world(inp: Annotated[dict, Json], *a_string) -> Annotated[dict, Json]:
    print("Hello from Python!")
    print(a_string)
    inp["roundtrip"] = 1
    return inp


# Compare against Python implementation.
def count_vowels(data):
    return sum(letter in b"AaEeIiOoUu" for letter in data)


def main(args):
    set_log_file("stderr", "trace")
    if len(args) > 1:
        data = args[1].encode()
    else:
        data = b"a" * 1024

    wasm_file_path = pathlib.Path(__file__).parent / "wasm" / "code-functions.wasm"
    wasm = wasm_file_path.read_bytes()
    hash = hashlib.sha256(wasm).hexdigest()
    manifest = {"wasm": [{"data": wasm, "hash": hash}]}

    plugin = Plugin(manifest, wasi=True)
    print(plugin.id)
    # Call `count_vowels`
    wasm_vowel_count = plugin.call("count_vowels", data)
    print(wasm_vowel_count)
    j = json.loads(wasm_vowel_count)

    print("Number of vowels:", j["count"])

    assert j["count"] == count_vowels(data)
    assert j["roundtrip"] == 1


if __name__ == "__main__":
    main(sys.argv)
