from collections import namedtuple
import gc
import hashlib
import json
import pickle
import time
import typing
import unittest
from datetime import datetime, timedelta
from os.path import join, dirname
from threading import Thread

import extism
from extism.extism import CompiledPlugin, _ExtismFunctionMetadata, TypeInferredFunction


# A pickle-able object.
class Gribble:
    def __init__(self, v):
        self.v = v

    def frobbitz(self):
        return "gromble %s" % self.v


class TestExtism(unittest.TestCase):
    def test_call_plugin(self):
        plugin = extism.Plugin(self._manifest(), functions=[])
        j = json.loads(plugin.call("count_vowels", "this is a test"))
        self.assertEqual(j["count"], 4)
        j = json.loads(plugin.call("count_vowels", "this is a test again"))
        self.assertEqual(j["count"], 7)
        j = json.loads(plugin.call("count_vowels", "this is a test thrice"))
        self.assertEqual(j["count"], 6)
        j = json.loads(plugin.call("count_vowels", "🌎hello🌎world🌎"))
        self.assertEqual(j["count"], 3)

    def test_function_exists(self):
        plugin = extism.Plugin(self._manifest(), functions=[])
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

    def test_plugin_del_frees_native_resources(self):
        """Test that Plugin.__del__ properly frees native resources.

        This tests the fix for a bug where Plugin.__del__ checked for
        'self.pointer' instead of 'self.plugin', causing extism_plugin_free
        to never be called and leading to memory leaks.

        This also tests that __del__ can be safely called multiple times
        (via context manager exit and garbage collection) without causing
        double-free errors.
        """
        with extism.Plugin(self._manifest(), functions=[]) as plugin:
            j = json.loads(plugin.call("count_vowels", "test"))
            self.assertEqual(j["count"], 1)
            # Plugin should own the compiled plugin it created
            self.assertTrue(plugin._owns_compiled_plugin)

        # Verify plugin was freed after exiting context
        self.assertEqual(
            plugin.plugin,
            -1,
            "Expected plugin.plugin to be -1 after __del__, indicating extism_plugin_free was called",
        )
        # Verify compiled plugin was also freed (since Plugin owned it)
        self.assertIsNone(
            plugin.compiled_plugin,
            "Expected compiled_plugin to be None after __del__, indicating it was also freed",
        )

    def test_compiled_plugin_del_frees_native_resources(self):
        """Test that CompiledPlugin.__del__ properly frees native resources.

        Unlike Plugin, CompiledPlugin has no context manager so __del__ is only
        called once by garbage collection. This also tests that __del__ can be
        safely called multiple times without causing double-free errors.
        """
        compiled = CompiledPlugin(self._manifest(), functions=[])
        # Verify pointer exists before deletion
        self.assertTrue(hasattr(compiled, "pointer"))
        self.assertNotEqual(compiled.pointer, -1)

        # Create a plugin from compiled to ensure it works
        plugin = extism.Plugin(compiled)
        j = json.loads(plugin.call("count_vowels", "test"))
        self.assertEqual(j["count"], 1)

        # Plugin should NOT own the compiled plugin (it was passed in)
        self.assertFalse(plugin._owns_compiled_plugin)

        # Clean up plugin first
        plugin.__del__()
        self.assertEqual(plugin.plugin, -1)

        # Compiled plugin should NOT have been freed by Plugin.__del__
        self.assertNotEqual(
            compiled.pointer,
            -1,
            "Expected compiled.pointer to NOT be -1 since Plugin didn't own it",
        )

        # Now clean up compiled plugin manually
        compiled.__del__()

        # Verify compiled plugin was freed
        self.assertEqual(
            compiled.pointer,
            -1,
            "Expected compiled.pointer to be -1 after __del__, indicating extism_compiled_plugin_free was called",
        )

    def test_extism_function_metadata_del_frees_native_resources(self):
        """Test that _ExtismFunctionMetadata.__del__ properly frees native resources."""

        def test_host_fn(inp: str) -> str:
            return inp

        func = TypeInferredFunction(None, "test_func", test_host_fn, [])
        metadata = _ExtismFunctionMetadata(func)

        # Verify pointer exists before deletion
        self.assertTrue(hasattr(metadata, "pointer"))
        self.assertIsNotNone(metadata.pointer)

        metadata.__del__()

        # Verify function was freed (pointer set to None)
        self.assertIsNone(
            metadata.pointer,
            "Expected metadata.pointer to be None after __del__, indicating extism_function_free was called",
        )

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
            *user_data,
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

    def test_host_context(self):
        if not hasattr(typing, "Annotated"):
            return

        # Testing two things here: one, if we see CurrentPlugin as the first arg, we pass it through.
        # Two, it's possible to refer to fetch the host context from the current plugin.
        @extism.host_fn(user_data=b"test")
        def hello_world(
            current_plugin: extism.CurrentPlugin,
            inp: typing.Annotated[dict, extism.Json],
            *user_data,
        ) -> typing.Annotated[Gribble, extism.Pickle]:
            ctx = current_plugin.host_context()
            ctx.x = 1000
            return Gribble("robble")

        plugin = extism.Plugin(
            self._manifest(functions=True), functions=[hello_world], wasi=True
        )

        class Foo:
            x = 100
            y = 200

        foo = Foo()

        res = plugin.call("count_vowels", "aaa", host_context=foo)

        self.assertEqual(foo.x, 1000)
        self.assertEqual(foo.y, 200)
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
