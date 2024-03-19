import unittest
import extism
import hashlib
import json
import time
from threading import Thread
from datetime import datetime, timedelta
from os.path import join, dirname
import typing
import pickle


# A pickle-able object.
class Gribble:
    def __init__(self, v):
        self.v = v

    def frobbitz(self):
        return "gromble %s" % self.v


class TestExtism(unittest.TestCase):
    def test_call_plugin(self):
        plugin = extism.Plugin(self._manifest())
        j = json.loads(plugin.call("count_vowels", "this is a test"))
        self.assertEqual(j["count"], 4)
        j = json.loads(plugin.call("count_vowels", "this is a test again"))
        self.assertEqual(j["count"], 7)
        j = json.loads(plugin.call("count_vowels", "this is a test thrice"))
        self.assertEqual(j["count"], 6)
        j = json.loads(plugin.call("count_vowels", "🌎hello🌎world🌎"))
        self.assertEqual(j["count"], 3)

    def test_function_exists(self):
        plugin = extism.Plugin(self._manifest())
        self.assertTrue(plugin.function_exists("count_vowels"))
        self.assertFalse(plugin.function_exists("i_dont_exist"))

    def test_errors_on_unknown_function(self):
        plugin = extism.Plugin(self._manifest())
        self.assertRaises(
            extism.Error, lambda: plugin.call("i_dont_exist", "someinput")
        )

    def test_can_free_plugin(self):
        plugin = extism.Plugin(self._manifest())
        del plugin

    def test_errors_on_bad_manifest(self):
        self.assertRaises(
            extism.Error, lambda: extism.Plugin({"invalid_manifest": True})
        )

    def test_extism_version(self):
        self.assertIsNotNone(extism.extism_version())

    def test_extism_plugin_timeout(self):
        plugin = extism.Plugin(self._loop_manifest())
        start = datetime.now()
        self.assertRaises(extism.Error, lambda: plugin.call("infinite_loop", b""))
        end = datetime.now()
        self.assertLess(
            end,
            start + timedelta(seconds=1.1),
            "plugin timeout exceeded 1000ms expectation",
        )

    def test_extism_host_function(self):
        @extism.host_fn(
            signature=([extism.ValType.I64], [extism.ValType.I64]), user_data=b"test"
        )
        def hello_world(plugin, params, results, user_data):
            offs = plugin.alloc(len(user_data))
            mem = plugin.memory(offs)
            mem[:] = user_data
            results[0].value = offs.offset

        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )
        res = plugin.call("count_vowels", "aaa")
        self.assertEqual(res, b"test")

    def test_inferred_extism_host_function(self):
        @extism.host_fn(user_data=b"test")
        def hello_world(inp: str, *user_data) -> str:
            return "hello world: %s %s" % (inp, user_data[0].decode("utf-8"))

        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )
        res = plugin.call("count_vowels", "aaa")
        self.assertEqual(res, b'hello world: {"count": 3} test')

    def test_inferred_json_param_extism_host_function(self):
        if not hasattr(typing, "Annotated"):
            return

        @extism.host_fn(user_data=b"test")
        def hello_world(inp: typing.Annotated[dict, extism.Json], *user_data) -> str:
            return "hello world: %s %s" % (inp["count"], user_data[0].decode("utf-8"))

        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )
        res = plugin.call("count_vowels", "aaa")
        self.assertEqual(res, b"hello world: 3 test")

    def test_codecs(self):
        if not hasattr(typing, "Annotated"):
            return

        @extism.host_fn(user_data=b"test")
        def hello_world(
            inp: typing.Annotated[
                str, extism.Codec(lambda xs: xs.decode().replace("o", "u"))
            ],
            *user_data
        ) -> typing.Annotated[
            str, extism.Codec(lambda xs: xs.replace("u", "a").encode())
        ]:
            return inp

        foo = b"bar"
        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )
        res = plugin.call("count_vowels", "aaa")
        # Iiiiiii
        self.assertEqual(res, b'{"caant": 3}')  # stand it, I know you planned it

    def test_inferred_pickle_return_param_extism_host_function(self):
        if not hasattr(typing, "Annotated"):
            return

        @extism.host_fn(user_data=b"test")
        def hello_world(
            inp: typing.Annotated[dict, extism.Json], *user_data
        ) -> typing.Annotated[Gribble, extism.Pickle]:
            return Gribble("robble")

        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )
        res = plugin.call("count_vowels", "aaa")

        result = pickle.loads(res)
        self.assertIsInstance(result, Gribble)
        self.assertEqual(result.frobbitz(), "gromble robble")

    def test_extism_plugin_cancel(self):
        plugin = extism.Plugin(self._loop_manifest())
        cancel_handle = plugin.cancel_handle()

        def cancel(handle):
            time.sleep(0.5)
            handle.cancel()

        Thread(target=cancel, args=[cancel_handle]).run()
        self.assertRaises(extism.Error, lambda: plugin.call("infinite_loop", b""))

    def _manifest(self, functions=False):
        wasm = self._count_vowels_wasm(functions)
        hash = hashlib.sha256(wasm).hexdigest()
        return {"wasm": [{"data": wasm, "hash": hash}]}

    def _loop_manifest(self):
        wasm = self._infinite_loop_wasm()
        hash = hashlib.sha256(wasm).hexdigest()
        return {
            "wasm": [{"data": wasm, "hash": hash}],
            "timeout_ms": 1000,
        }

    def _count_vowels_wasm(self, functions=False):
        return read_test_wasm("code.wasm" if not functions else "code-functions.wasm")

    def _infinite_loop_wasm(self):
        return read_test_wasm("loop.wasm")


def read_test_wasm(p):
    path = join(dirname(__file__), "..", "wasm", p)
    with open(path, "rb") as wasm_file:
        return wasm_file.read()

    
# pool = Pool(max_instances=5)
# manifest = {'wasm': [{'path': 'code.wasm'}]}
# pool.add('test', lambda: Plugin(manifest, wasi=True))

# def run_test(sleep, input):
#     with pool.get('test') as plugin:
#         time.sleep(sleep)
#         print(plugin.call('count_vowels', input))

# def test_thread(sleep, input):
#     t = Thread(target=run_test, args=[sleep, input])
#     t.start()
#     return t

# threads = [
#     test_thread(1, 'aaa'),
#     test_thread(1, 'aaa'),
#     test_thread(1, 'aaa'),
#     test_thread(1, 'aaa'),
#     test_thread(1, 'aaa'),
#     test_thread(1, 'aaa'),
#     test_thread(2, ''),
#     test_thread(2, ''),
#     test_thread(2, ''),
#     test_thread(2, ''),
#     test_thread(2, ''),
#     test_thread(2, ''),
#     test_thread(0, 'abc'),
#     test_thread(0, 'abc'),
#     test_thread(0, 'abc'),
#     test_thread(0, 'abc'),
#     test_thread(0, 'abc'),
#     test_thread(0, 'abc'),
# ]

# for t in threads:
#     t.join()

# async def test_async_inner(sleep, input):
#     with await pool.get('test') as plugin:
#         await asyncio.sleep(sleep)
#         print(plugin.call('count_vowels', input))

# async def test_async(*args):
#     await asyncio.create_task(test_async_inner(*args))

# futures = [
#     test_async(1, 'aaa'),
#     test_async(1, 'aaa'),
#     test_async(1, 'aaa'),
#     test_async(1, 'aaa'),
#     test_async(1, 'aaa'),
#     test_async(1, 'aaa'),
#     test_async(2, ''),
#     test_async(2, ''),
#     test_async(2, ''),
#     test_async(2, ''),
#     test_async(2, ''),
#     test_async(2, ''),
#     test_async(0, 'abc'),
#     test_async(0, 'abc'),
#     test_async(0, 'abc'),
#     test_async(0, 'abc'),
#     test_async(0, 'abc'),
#     test_async(0, 'abc'),
# ]

# async def main():
#     await asyncio.gather(*futures)

# asyncio.get_event_loop().run_until_complete(main())
