import json
import os
from base64 import b64encode
import typing
from typing import (
    get_args,
    get_origin,
    get_type_hints,
    Any,
    Callable,
    List,
    Union,
    Literal,
    Optional,
    Tuple,
)
from enum import Enum
from uuid import UUID
from extism_sys import lib as _lib, ffi as _ffi  # type: ignore
import functools
import pickle


HOST_FN_REGISTRY: List[Any] = []


class Json:
    """
    Typing metadata: indicates that an extism host function parameter (or return value)
    should be encoded (or decoded) using ``json``.

    .. sourcecode:: python

        @extism.host_fn()
        def load(input: typing.Annotated[dict, extism.Json]):
            # input will be a dictionary decoded from json input.
            input.get("hello", None)

        @extism.host_fn()
        def load(input: int) -> typing.Annotated[dict, extism.Json]:
            return {
                'hello': 3
            }

    """

    ...


class Pickle:
    """
    Typing metadata: indicates that an extism host function parameter (or return value)
    should be encoded (or decoded) using ``pickle``.

    .. sourcecode:: python

        class Grimace:
            ...

        @extism.host_fn()
        def load(input: typing.Annotated[Grimace, extism.Pickle]):
            # input will be an instance of Grimace!
            ...

        @extism.host_fn()
        def load(input: int) -> typing.Annotated[Grimace, extism.Pickle]:
            return Grimace()

    """

    ...


class Codec:
    """
    Typing metadata: indicates that an extism host function parameter (or return value)
    should be transformed with the provided function.

    .. sourcecode:: python

        import json

        @extism.host_fn()
        def load(input: typing.Annotated[str, extism.Codec(lambda inp: inp.decode(encoding = 'shift_jis'))]):
            # you can accept shift-jis bytes as input!
            ...

        mojibake_factory = lambda out: out.encode(encoding='utf8').decode(encoding='latin1').encode()

        @extism.host_fn()
        def load(input: int) -> typing.Annotated[str, extism.Codec(mojibake_factory)]:
            return "get ready for some mojibake 🎉"
    """

    def __init__(self, codec):
        self.codec = codec


class Error(Exception):
    """
    A subclass of :py:class:`Exception <Exception>` representing a failed guest function call.
    Contains one argument: the error output.
    """

    ...


class ValType(Enum):
    """
    An enumeration of all available `Wasm value types <https://docs.rs/wasmtime/latest/wasmtime/enum.ValType.html>`.

    `PTR` is an alias for `I64` to make typing a little less confusing when writing host function definitions
    """

    I32 = 0
    PTR = 1
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

    def _assign(self, v):
        self.value = v


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


class CustomLogger:
    def __init__(self, f):
        self.callback = None
        self.set_callback(f)

    def set_callback(self, f):
        @_ffi.callback("void(char*, ExtismSize)")
        def callback(ptr, len):
            f(_ffi.string(ptr, len).decode())

        self.callback = callback

    def drain(self):
        if self.callback is not None:
            _lib.extism_log_drain(self.callback)

    def __del__(self):
        self.drain()


def set_log_custom(
    f, level: Optional[Literal["debug", "error", "trace", "warn"]] = None
):
    """
    Enables buffered logging, this is a global configuration

    :param f: The callback function, takes a string argument and no return value.
    :param level: The debug level.

    :returns: a CustomLogger with a `drain` method that can be used to handle the buffered logs.
    """
    c_level = level or _ffi.NULL
    if isinstance(level, str):
        c_level = level.encode()

    _lib.extism_log_custom(c_level)
    return CustomLogger(f)


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

    def __init__(
        self, namespace: Optional[str], name: str, args, returns, f, *user_data
    ):
        self.namespace = namespace
        self.name = name
        self.args = [a.value for a in args]
        self.returns = [r.value for r in returns]
        if len(user_data) > 0:
            self.user_data = _ffi.new_handle(user_data)
        else:
            self.user_data = _ffi.NULL
        self.f = f


class _ExtismFunctionMetadata:
    def __init__(self, f: Function):
        self.pointer = _lib.extism_function_new(
            f.name.encode(),
            f.args,
            len(f.args),
            f.returns,
            len(f.returns),
            f.f,
            f.user_data,
            _ffi.NULL,
        )
        if f.namespace is not None:
            _lib.extism_function_set_namespace(self.pointer, f.namespace.encode())

    def __del__(self):
        if not hasattr(self, "pointer"):
            return
        if self.pointer is not None:
            _lib.extism_function_free(self.pointer)


def _map_arg(arg_name, xs) -> Tuple[ValType, Callable[[Any, Any], Any]]:
    if xs == str:
        return (ValType.I64, lambda plugin, slot: plugin.input_string(slot))

    if xs == bytes:
        return (ValType.I64, lambda plugin, slot: plugin.input_bytes(slot))

    if xs == int:
        return (ValType.I64, lambda _, slot: slot.value)

    if xs == float:
        return (ValType.F64, lambda _, slot: slot.value)

    if xs == bool:
        return (ValType.I32, lambda _, slot: slot.value)

    metadata = getattr(xs, "__metadata__", ())
    for item in metadata:
        if item == Json:
            return (
                ValType.I64,
                lambda plugin, slot: json.loads(plugin.input_string(slot)),
            )

        if item == Pickle:
            return (
                ValType.I64,
                lambda plugin, slot: pickle.loads(plugin.input_bytes(slot)),
            )

        if isinstance(item, Codec):
            return (
                ValType.I64,
                lambda plugin, slot: item.codec(plugin.input_bytes(slot)),
            )

    raise TypeError("Could not infer input type for argument %s" % arg_name)


def _map_ret(xs) -> List[Tuple[ValType, Callable[[Any, Any, Any], Any]]]:
    if xs == str:
        return [
            (ValType.I64, lambda plugin, slot, value: plugin.return_string(slot, value))
        ]

    if xs == bytes:
        return [
            (ValType.I64, lambda plugin, slot, value: plugin.return_bytes(slot, value))
        ]

    if xs == int:
        return [(ValType.I64, lambda _, slot, value: slot.assign(value))]

    if xs == float:
        return [(ValType.F64, lambda _, slot, value: slot.assign(value))]

    if xs == bool:
        return [(ValType.I32, lambda _, slot, value: slot.assign(value))]

    if get_origin(xs) == tuple:
        return functools.reduce(lambda lhs, rhs: lhs + _map_ret(rhs), get_args(xs), [])

    metadata = getattr(xs, "__metadata__", ())
    for item in metadata:
        if item == Json:
            return [
                (
                    ValType.I64,
                    lambda plugin, slot, value: plugin.return_string(
                        slot, json.dumps(value)
                    ),
                )
            ]

        if item == Pickle:
            return [
                (
                    ValType.I64,
                    lambda plugin, slot, value: plugin.return_bytes(
                        slot, pickle.dumps(value)
                    ),
                )
            ]

        if isinstance(item, Codec):
            return [
                (
                    ValType.I64,
                    lambda plugin, slot, value: plugin.return_bytes(
                        slot, item.codec(value)
                    ),
                )
            ]

    raise TypeError("Could not infer return type")


class ExplicitFunction(Function):
    def __init__(self, namespace, name, args, returns, func, user_data):
        self.func = func

        super().__init__(namespace, name, args, returns, handle_args, *user_data)

        functools.update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


class TypeInferredFunction(ExplicitFunction):
    def __init__(self, namespace, name, func, user_data):
        kwargs: dict[str, Any] = {}
        if hasattr(typing, "Annotated"):
            kwargs["include_extras"] = True

        hints = get_type_hints(func, **kwargs)
        if len(hints) == 0:
            raise TypeError(
                "Host function must include Python type annotations or explicitly list arguments."
            )

        arg_names = [arg for arg in hints.keys() if arg != "return"]
        returns = hints.pop("return", None)

        uses_current_plugin = False
        if len(arg_names) > 0 and hints.get(arg_names[0], None) == CurrentPlugin:
            uses_current_plugin = True
            arg_names = arg_names[1:]

        args = [_map_arg(arg, hints[arg]) for arg in arg_names]

        returns = [] if returns is None else _map_ret(returns)

        def inner_func(plugin, inputs, outputs, *user_data):
            first_arg = [plugin] if uses_current_plugin else []
            inner_args = first_arg + [
                extract(plugin, slot) for ((_, extract), slot) in zip(args, inputs)
            ]

            if user_data is not None:
                inner_args += list(user_data)

            result = func(*inner_args)
            for (_, emplace), slot in zip(returns, outputs):
                emplace(plugin, slot, result)

        super().__init__(
            namespace,
            name,
            [typ for (typ, _) in args],
            [typ for (typ, _) in returns],
            inner_func,
            user_data,
        )


class CancelHandle:
    def __init__(self, ptr):
        self.pointer = ptr

    def cancel(self) -> bool:
        return _lib.extism_plugin_cancel(self.pointer)


class CompiledPlugin:
    """
    A ``CompiledPlugin`` represents a parsed Wasm module and associated Extism
    kernel. It can be used to rapidly instantiate plugin instances. A ``Plugin``
    instantiated with a ``CompiledPlugin`` inherits the functions and WASI settings
    of the compiled plugin.

    .. sourcecode:: python

        import extism

        compiled = extism.CompiledPlugin({
            wasm: [
                { 'url': 'https://example.com/path/to/module.wasm' }
            ],
        })

        plugin = extism.Plugin(compiled)
        plugin.call("example-function")
    """

    def __init__(
        self,
        plugin: Union[str, bytes, dict],
        wasi: bool = False,
        functions: Optional[List[Function]] = HOST_FN_REGISTRY,
    ):
        wasm = _wasm(plugin)
        self.functions = functions
        as_extism_functions = [_ExtismFunctionMetadata(f) for f in functions or []]
        as_ptrs = [f.pointer for f in as_extism_functions]
        # Register plugin
        errmsg = _ffi.new("char**")
        function_ptrs = (
            _ffi.NULL if len(as_ptrs) == 0 else _ffi.new("ExtismFunction*[]", as_ptrs)
        )
        self.pointer = _lib.extism_compiled_plugin_new(
            wasm, len(wasm), function_ptrs, len(as_ptrs), wasi, errmsg
        )

        if self.pointer == _ffi.NULL:
            msg = _ffi.string(errmsg[0])
            _lib.extism_plugin_new_error_free(errmsg[0])
            raise Error(msg.decode())

    def __del__(self):
        if not hasattr(self, "pointer"):
            return
        _lib.extism_compiled_plugin_free(self.pointer)
        self.pointer = -1


class Plugin:
    """
    Plugins are used to call WASM functions. Plugins can kept in a context for
    as long as you need. They may be freed with the ``del`` keyword.

    .. sourcecode:: python

        import extism

        with extism.Plugin({
            # all three of these wasm modules will be instantiated and their exported functions
            # made available to the `plugin` variable below.
            wasm: [
                { 'url': 'https://example.com/path/to/module.wasm' }
                { 'data': b'\\xde\\xad\\xbe\\xef' } # byte content representing a wasm module
                { 'url': 'https://example.com/path/to/module.wasm', hash: 'cafebeef' } # check that the downloaded module matches a specified sha256 hash.
            ],
        }) as plugin:
            plugin.call("example-function")

    :param plugin: Plugin data, passed as bytes representing a single WebAssembly module,
                   a string representing a serialized JSON `Manifest <https://extism.org/docs/concepts/manifest/>`_, or
                   a dict respresenting a deserialized `Manifest <https://extism.org/docs/concepts/manifest/>`_.
    :param wasi: Indicates whether WASI preview 1 support will be enabled for this plugin.
    :param config: An optional JSON-serializable object holding a map of configuration keys
                   and values.
    :param functions: An optional list of host :py:class:`functions <.extism.Function>` to
                      expose to the guest program. Defaults to all registered ``@host_fn()``'s
                      if not given.
    """

    def __init__(
        self,
        plugin: Union[str, bytes, CompiledPlugin, dict],
        wasi: bool = False,
        config: Optional[Any] = None,
        functions: Optional[List[Function]] = HOST_FN_REGISTRY,
    ):
        if not isinstance(plugin, CompiledPlugin):
            plugin = CompiledPlugin(plugin, wasi, functions)

        self.compiled_plugin = plugin
        errmsg = _ffi.new("char**")

        self.plugin = _lib.extism_plugin_new_from_compiled(
            self.compiled_plugin.pointer, errmsg
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
        error = _lib.extism_plugin_error(self.plugin)
        if error != _ffi.NULL:
            raise Error(_ffi.string(error).decode())
        if rc != 0:
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
        host_context: Any = None,
    ) -> Any:
        """
        Call a function by name with the provided input data

        :param function_name: The name of the function to invoke
        :param data: The input data to the function.
        :param parse: The function used to parse the buffer returned by the guest function call. Defaults to :py:class:`bytes <bytes>`.
        :raises: An :py:class:`extism.Error <.extism.Error>` if the guest function call was unsuccessful.
        :returns: The returned bytes from the guest function as interpreted by the ``parse`` parameter.
        """

        host_context = _ffi.new_handle(host_context)
        if isinstance(data, str):
            data = data.encode()
        self._check_error(
            _lib.extism_plugin_call_with_host_context(
                self.plugin, function_name.encode(), data, len(data), host_context
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

    def host_context(self) -> Any:
        result = _lib.extism_current_plugin_host_context(self.pointer)
        if result == 0:
            return None
        return _ffi.from_handle(result)

    def alloc(self, size: int) -> Memory:
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

           @extism.host_fn(signature=([extism.ValType.PTR], []))
           def hello_world(plugin, params, results):
               my_str = plugin.input_string(params[0])
               print(my_str)

           # assume the following wasm file exists:
           # example.wat = \"""
           # (module
           #     (import "example" "hello_world" (func $hello (param i64)))
           #     (import "extism:host/env" "alloc" (func $extism_alloc (param i64) (result i64)))
           #     (import "extism:host/env" "store_u8" (func $extism_store_u8 (;6;) (param i64 i32)))
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

           with extism.Plugin(data, functions=[hello_world]) as plugin:
               plugin.call("my_func", "")

        :param input: The input value that references a string.
        """
        return self.input_bytes(input).decode()


def host_fn(
    name: Optional[str] = None,
    namespace: Optional[str] = None,
    signature: Optional[Tuple[List[ValType], List[ValType]]] = None,
    user_data: Optional[Union[bytes, List[bytes]]] = None,
):
    """
    A decorator for creating host functions. Host functions are installed into a thread-local
    registry.

    :param name: The function name to expose to the guest plugin. If not given, inferred from the
                 wrapped function name.
    :param namespace: The namespace to install the function into; defaults to "extism:host/user" if not given.
    :param signature: A tuple of two arrays representing the function parameter types and return value types.
                      If not given, types will be inferred from ``typing`` annotations.
    :param userdata: Any custom userdata to associate with the function.

    Supported Inferred Types
    ------------------------

    - ``typing.Annotated[Any, extism.Json]``: In both parameter and return
      positions. Written to extism memory; offset encoded in return value as
      ``I64``.
    - ``typing.Annotated[Any, extism.Pickle]``: In both parameter and return
      positions. Written to extism memory; offset encoded in return value as
      ``I64``.
    - ``str``, ``bytes``: In both parameter and return
      positions. Written to extism memory; offset encoded in return value as
      ``I64``.
    - ``int``:  In both parameter and return positions. Encoded as ``I64``.
    - ``float``: In both parameter and return positions. Encoded as ``F64``.
    - ``bool``: In both parameter and return positions. Encoded as ``I32``.
    - ``typing.Tuple[<any of the above types>]``: In return position; expands
      return list to include all member type encodings.

    .. sourcecode:: python

        import typing
        import extism

        @extism.host_fn()
        def greet(who: str) -> str:
            return "hello %s" % who

        @extism.host_fn()
        def load(input: typing.Annotated[dict, extism.Json]) -> typing.Tuple[int, int]:
            # input will be a dictionary decoded from json input. The tuple will be returned
            # two I64 values.
            return (3, 4)

        @extism.host_fn()
        def return_many_encoded() -> typing.Tuple(int, typing.Annotated[dict, extism.Json]):
            # we auto-encoded any Json-annotated return values, even in a tuple
            return (32, {"hello": "world"})

        class Gromble:
            ...

        @extism.host_fn()
        def everyone_loves_a_pickle(grumble: typing.Annotated[Gromble, extism.Pickle]) -> typing.Annotated[Gromble, extism.Pickle]:
            # you can pass pickled objects in and out of host funcs
            return Gromble()

        @extism.host_fn(signature=([extism.ValType.PTR], []))
        def more_control(
            current_plugin: extism.CurrentPlugin,
            params: typing.List[extism.Val],
            results: typing.List[extism.Val],
            *user_data
        ):
            # if you need more control, you can specify the wasm-level input
            # and output types explicitly.
            ...

    """
    if user_data is None:
        user_data = []
    elif isinstance(user_data, bytes):
        user_data = [user_data]

    def outer(func):
        n = name or func.__name__

        idx = len(HOST_FN_REGISTRY).to_bytes(length=4, byteorder="big")
        user_data.append(idx)
        fn = (
            TypeInferredFunction(namespace, n, func, user_data)
            if signature is None
            else ExplicitFunction(
                namespace, n, signature[0], signature[1], func, user_data
            )
        )
        HOST_FN_REGISTRY.append(fn)
        return fn

    return outer


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

    if user_data == _ffi.NULL:
        udata = []
    else:
        udata = list(_ffi.from_handle(user_data))

    idx = int.from_bytes(udata.pop(), byteorder="big")

    HOST_FN_REGISTRY[idx](CurrentPlugin(current), inp, outp, *udata)

    for i in range(n_outputs):
        _convert_output(outputs[i], outp[i])
