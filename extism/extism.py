import json
import os
from base64 import b64encode
from cffi import FFI
from typing import Any, Callable, Dict, List, Union, Literal, Optional
from enum import Enum
from uuid import UUID
from extism_sys import lib as _lib, ffi as _ffi  # type: ignore
from typing import Annotated
from annotated_types import Gt


class Error(Exception):
    """
    A subclass of :py:class:`Exception <Exception>` representing a failed guest function call.
    Contains one argument: the error output.
    """

    ...


class _Base64Encoder(json.JSONEncoder):
    # pylint: disable=method-hidden
    def default(self, o):
        if isinstance(o, bytes):
            return b64encode(o).decode()
        return json.JSONEncoder.default(self, o)


def set_log_file(
    file: str, level: Optional[Literal["debug", "error", "trace", "warn"]] = None
):
    """
    Sets the log file and level, this is a global configuration

    :param file: The path to the logfile
    :param level: The debug level.
    """
    c_level = level or _ffi.NULL
    if isinstance(level, str):
        c_level = level.encode()
    _lib.extism_log_file(file.encode(), c_level)


def extism_version() -> str:
    """
    Gets the Extism version string

    :returns: The Extism runtime version string
    """
    return _ffi.string(_lib.extism_version()).decode()


def _wasm(plugin):
    if isinstance(plugin, str) and os.path.exists(plugin):
        with open(plugin, "rb") as f:
            wasm = f.read()
    elif isinstance(plugin, str):
        wasm = plugin.encode()
    elif isinstance(plugin, dict):
        wasm = json.dumps(plugin, cls=_Base64Encoder).encode()
    else:
        wasm = plugin
    return wasm


class Memory:
    """
    A reference to plugin memory.
    """

    def __init__(self, offs, length):
        self.offset = offs
        self.length = length

    def __len__(self):
        return self.length


class Function:
    """
    A host function.
    """

    def __init__(self, name: str, args, returns, f, *user_data):
        self.pointer = None
        args = [a.value for a in args]
        returns = [r.value for r in returns]
        if len(user_data) > 0:
            self.user_data = _ffi.new_handle(user_data)
        else:
            self.user_data = _ffi.NULL
        self.pointer = _lib.extism_function_new(
            name.encode(),
            args,
            len(args),
            returns,
            len(returns),
            f,
            self.user_data,
            _ffi.NULL,
        )

    def set_namespace(self, name: str):
        _lib.extism_function_set_namespace(self.pointer, name.encode())

    def with_namespace(self, name: str):
        self.set_namespace(name)
        return self

    def __del__(self):
        if not hasattr(self, "pointer"):
            return
        if self.pointer is not None:
            _lib.extism_function_free(self.pointer)


class CancelHandle:
    def __init__(self, ptr):
        self.pointer = ptr

    def cancel(self) -> bool:
        return _lib.extism_plugin_cancel(self.pointer)


class Plugin:
    """
    Plugins are used to call WASM functions. Plugins can kept in a context for
    as long as you need. They may be freed with the ``del`` keyword.

    :param plugin: The path to the logfile
    :param wasi: Indicates whether WASI preview 1 support will be enabled for this plugin.
    :param config: An optional JSON-serializable object holding a map of configuration keys
                   and values.
    :param functions: An optional list of host :py:class:`functions <.extism.Function>` to
                      expose to the guest program.
    """

    def __init__(
        self,
        plugin: Union[str, bytes, dict],
        wasi: bool = False,
        config: Optional[Any] = None,
        functions: Optional[List[Function]] = None,
    ):
        wasm = _wasm(plugin)
        self.functions = functions

        # Register plugin
        errmsg = _ffi.new("char**")
        if functions is not None:
            function_ptrs = [f.pointer for f in functions]
            ptr = _ffi.new("ExtismFunction*[]", function_ptrs)
            self.plugin = _lib.extism_plugin_new(
                wasm, len(wasm), ptr, len(function_ptrs), wasi, errmsg
            )
        else:
            self.plugin = _lib.extism_plugin_new(
                wasm, len(wasm), _ffi.NULL, 0, wasi, errmsg
            )

        if self.plugin == _ffi.NULL:
            msg = _ffi.string(errmsg[0])
            _lib.extism_plugin_new_error_free(errmsg[0])
            raise Error(msg.decode())

        if config is not None:
            s = json.dumps(config).encode()
            _lib.extism_plugin_config(self.plugin, s, len(s))

    @property
    def id(self) -> UUID:
        b = bytes(_ffi.unpack(_lib.extism_plugin_id(self.plugin), 16))
        return UUID(bytes=b)

    def cancel_handle(self):
        return CancelHandle(_lib.extism_plugin_cancel_handle(self.plugin))

    def _check_error(self, rc):
        if rc != 0:
            error = _lib.extism_plugin_error(self.plugin)
            if error != _ffi.NULL:
                raise Error(_ffi.string(error).decode())
            raise Error(f"Error code: {rc}")

    def function_exists(self, name: str) -> bool:
        """
        Given a function name, check whether the name is exported from this function.

        :param name: The function name to query.
        """
        return _lib.extism_plugin_function_exists(self.plugin, name.encode())

    def call(
        self,
        function_name: str,
        data: Union[str, bytes],
        parse: Callable[[Any], Any] = lambda xs: bytes(xs),
    ):
        """
        Call a function by name with the provided input data

        :param function_name: The name of the function to invoke
        :param data: The input data to the function.
        :param parse: The function used to parse the buffer returned by the guest function call. Defaults to :py:class:`bytes <bytes>`.
        :raises: An :py:class:`extism.Error <.extism.Error>` if the guest function call was unsuccessful.
        :returns: The returned bytes from the guest function as interpreted by the ``parse`` parameter.
        """
        if isinstance(data, str):
            data = data.encode()
        self._check_error(
            _lib.extism_plugin_call(
                self.plugin, function_name.encode(), data, len(data)
            )
        )
        out_len = _lib.extism_plugin_output_length(self.plugin)
        out_buf = _lib.extism_plugin_output_data(self.plugin)
        buf = _ffi.buffer(out_buf, out_len)
        if parse is None:
            return buf
        return parse(buf)

    def __del__(self):
        if not hasattr(self, "pointer"):
            return
        _lib.extism_plugin_free(self.plugin)
        self.plugin = -1

    def __enter__(self):
        return self

    def __exit__(self, type, exc, traceback):
        self.__del__()


def _convert_value(x):
    if x.t == 0:
        return Val(ValType.I32, x.v.i32)
    elif x.t == 1:
        return Val(ValType.I64, x.v.i64)
    elif x.t == 2:
        return Val(ValType.F32, x.v.f32)
    elif x.y == 3:
        return Val(ValType.F64, x.v.f64)
    return None


def _convert_output(x, v):
    if v.t.value != x.t:
        raise Error(f"Output type mismatch, got {v.t} but expected {x.t}")

    if v.t == ValType.I32:
        x.v.i32 = int(v.value)
    elif v.t == ValType.I64:
        x.v.i64 = int(v.value)
    elif x.t == ValType.F32:
        x.v.f32 = float(v.value)
    elif x.t == ValType.F64:
        x.v.f64 = float(v.value)
    else:
        raise Error("Unsupported return type: " + str(x.t))


class ValType(Enum):
    """
    An enumeration of all available `Wasm value types <https://docs.rs/wasmtime/latest/wasmtime/enum.ValType.html>`_.
    """

    I32 = 0
    I64 = 1
    F32 = 2
    F64 = 3
    V128 = 4
    FUNC_REF = 5
    EXTERN_REF = 6


class Val:
    """
    Low-level WebAssembly value with associated :py:class:`ValType`.
    """

    def __init__(self, t: ValType, v):
        self.t = t
        self.value = v

    def __repr__(self):
        return f"Val({self.t}, {self.value})"


class CurrentPlugin:
    """
    This object is accessible when calling from the guest :py:class:`Plugin` into the host via
    a host :py:class:`Function`. It provides plugin memory access to host functions.
    """

    def __init__(self, p):
        self.pointer = p

    def memory(self, mem: Memory) -> _ffi.buffer:
        """
        Given a reference to plugin memory, return an FFI buffer

        :param mem: A memory reference to be accessed
        """
        p = _lib.extism_current_plugin_memory(self.pointer)
        if p == 0:
            return None
        return _ffi.buffer(p + mem.offset, mem.length)

    def alloc(self, size: Annotated[int, Gt(-1)]) -> Memory:
        """
        Allocate a new block of memory.

        :param size: The number of bytes to allocate. Must be a positive integer.
        """
        offs = _lib.extism_current_plugin_memory_alloc(self.pointer, size)
        return Memory(offs, size)

    def free(self, mem: Memory):
        """Free a block of memory by :py:class:`Memory <.Memory>` reference"""
        return _lib.extism_current_plugin_memory_free(self.pointer, mem.offset)

    def memory_at_offset(self, offs: Union[int, Val]) -> Memory:
        """Given a memory offset, return the corresponding a :py:class:`Memory <.Memory>` reference."""
        if isinstance(offs, Val):
            offs = offs.value
        len = _lib.extism_current_plugin_memory_length(self.pointer, offs)
        return Memory(offs, len)

    def return_bytes(self, output: Val, b: bytes):
        """
        A shortcut for returning :py:class:`bytes` from a host function.

        :param output: This argument will be **mutated** and made to hold the memory address of ``b``.
        :param b: The bytes to return.
        """
        mem = self.alloc(len(b))
        self.memory(mem)[:] = b
        output.value = mem.offset

    def return_string(self, output: Val, s: str):
        """
        A shortcut for returning :py:class:`str` from a host function.

        :param output: This argument will be **mutated** and made to hold the memory address of ``s``.
        :param s: The string to return.
        """
        self.return_bytes(output, s.encode())

    def input_buffer(self, input: Val):
        mem = self.memory_at_offset(input)
        return self.memory(mem)

    def input_bytes(self, input: Val) -> bytes:
        """
        A shortcut for accessing :py:class:`bytes` passed at the :py:class:`input <.Val>` parameter.

        :param input: The input value that references bytes.
        """
        return self.input_buffer(input)[:]

    def input_string(self, input: Val) -> str:
        """
        A shortcut for accessing :py:class:`str` passed at the :py:class:`input <.Val>` parameter.

        .. sourcecode:: python

           @extism.host_fn
           def hello_world(plugin, params, results):
               my_str = plugin.input_string(params[0])
               print(my_str)

           # assume the following wasm file exists:
           # example.wat = \"""
           # (module
           #     (import "example" "hello_world" (func $hello (param i64)))
           #     (import "env" "extism_alloc" (func $extism_alloc (param i64) (result i64)))
           #     (import "env" "extism_store_u8" (func $extism_store_u8 (;6;) (param i64 i32)))
           #
           #     (memory $memory (export "mem")
           #       (data "Hello from WAT!\00")
           #     )
           #     (func $my_func (result i64)
           #
           #       ;; allocate extism memory and copy our message into it
           #       (local $offset i64) (local $i i32)
           #       (local.set $offset (call $extism_alloc (i64.const 15)))
           #       (block $end
           #         (loop $loop
           #           (br_if $end (i32.eq (i32.const 0) (i32.load8_u (local.get $i))))
           #           (call $extism_store_u8 (i64.add (local.get $offset) (i64.extend_i32_u (local.get $i))) (i32.load8_u (local.get $i)))
           #           (local.set $i (i32.add (i32.const 1) (local.get $i)))
           #           br $loop
           #         )
           #       )
           #
           #       ;; call our hello_world function with our extism memory offset.
           #       local.get $offset
           #       call $hello
           #       i64.const 0
           #     )
           #     (export "my_func" (func $my_func))
           # )
           # \"""
           # ... and we've compiled it using "wasm-tools parse example.wat -o example.wasm"
           with open("example.wasm", "rb") as wasm_file:
               data = wasm_file.read()

           with extism.Plugin(data, functions=[
               extism.Function("hello_world", [extism.ValType.I64], [], hello_world).with_namespace("example")
           ]) as plugin:
               plugin.call("my_func", "")

        :param input: The input value that references a string.
        """
        return self.input_bytes(input).decode()


def host_fn(
    func: Union[
        Any,
        Callable[[CurrentPlugin, List[Val], List[Val]], List[Val]],
        Callable[[CurrentPlugin, List[Val], List[Val], Optional[Any]], List[Val]],
    ]
):
    """
    A decorator for creating host functions, this decorator wraps a function
    that takes the following parameters:

    - ``current_plugin``: :py:class:`CurrentPlugin <.CurrentPlugin>`
    - ``inputs``: :py:class:`List[Val] <.Val>`
    - ``outputs``: :py:class:`List[Val] <.Val>`
    - ``user_data``: any number of values passed as user data

    The function should return a list of `Val`.
    """

    @_ffi.callback(
        "void(ExtismCurrentPlugin*, const ExtismVal*, ExtismSize, ExtismVal*, ExtismSize, void*)"
    )
    def handle_args(current, inputs, n_inputs, outputs, n_outputs, user_data):
        inp = []
        outp = []

        for i in range(n_inputs):
            inp.append(_convert_value(inputs[i]))

        for i in range(n_outputs):
            outp.append(_convert_value(outputs[i]))

        cast_func: Any = func

        if user_data == _ffi.NULL:
            cast_func(CurrentPlugin(current), inp, outp)
        else:
            udata = _ffi.from_handle(user_data)
            cast_func(CurrentPlugin(current), inp, outp, *udata)

        for i in range(n_outputs):
            _convert_output(outputs[i], outp[i])

    return handle_args
