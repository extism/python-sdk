Usage
=====

.. currentmodule:: extism

This guide will walk you through Extism concepts using the Python SDK.

.. _installation:

Installation
------------

To use extism, first install it using pip:

.. code-block:: console

   (.venv) $ pip install extism

.. _getting_started:

Getting Started
---------------

To start, let's use a pre-existing WebAssembly module. We'll define a `Manifest
<https://extism.org/docs/concepts/manifest/#schema>`_ that pulls a pre-compiled
Wasm module down from the web. In this case, we'll start with a vowel counting
module:

.. sourcecode:: python
    :linenos:

    import extism
    import json

    manifest = {
        "wasm": [
            {
                "url": "https://github.com/extism/plugins/releases/download/v0.3.0/count_vowels.wasm",
                # Note the hash! We use this to ensure that the remote file matches what we expect.
                # If the remote version changes, the plugin will raise an `extism.Error` when we try
                # to construct it.
                "hash": "cf29364cb62d3bc4de8654b187fae9cf50174634760eb995b1745650e7a38b41"
            }
        ]
    }
    with extism.Plugin(manifest, wasi=True) as plugin:
        ...

Let's call a Wasm function from the module. Our example module exports a single
guest function, ``count_vowels``:

.. sourcecode:: python
    :linenos:
    :lineno-start: 15

    with extism.Plugin(manifest, wasi=True) as plugin:
        wasm_vowel_count = plugin.call(
            "count_vowels",
            "hello world",
        )
        print(wasm_vowel_count) # b'{"count": 3, "total": 3, "vowels": "aeiouAEIOU"}'

All Extism guest functions have a simple "bytes-in", "bytes-out" interface. In this case,
the input is a utf-8 encoded string, and the output is a utf-8 encoded string containing
JSON. We can pass a ``parse`` parameter to ``call`` to automatically decode the output for
us:

.. sourcecode:: python
    :linenos:
    :lineno-start: 15

    with extism.Plugin(manifest, wasi=True) as plugin:

        wasm_vowel_count = plugin.call(
            "count_vowels",
            "hello world",
            parse = lambda output: json.loads(
              bytes(output).decode('utf-8')
            )
        )
        print(wasm_vowel_count) # {'count': 3, 'total': 3, 'vowels': 'aeiouAEIOU'}


State and Configuration
~~~~~~~~~~~~~~~~~~~~~~~

Plugins may keep track of their own state:

.. sourcecode:: python
    :linenos:
    :lineno-start: 15

    with extism.Plugin(manifest, wasi=True) as plugin:
        [print(plugin.call(
            "count_vowels",
            "hello world",
            parse = lambda output: json.loads(
              bytes(output).decode('utf-8')
            )
        )['total']) for _ in range(0, 3)] # prints 3, 6, 9

    # if we re-instantiate the plugin, however, we reset the count:
    with extism.Plugin(manifest, wasi=True) as plugin:
        [print(plugin.call(
            "count_vowels",
            "hello world",
            parse = lambda output: json.loads(
              bytes(output).decode('utf-8')
            )
        )['total']) for _ in range(0, 3)] # prints 3, 6, 9 all over again

We can also statically configure values for use by the guest:

.. sourcecode:: python
    :linenos:
    :lineno-start: 15

    with extism.Plugin(manifest, wasi=True) as plugin:
        print(plugin.call(
            "count_vowels",
            "hello world",
            config = {'vowels': 'h'}
            parse = lambda output: json.loads(
              bytes(output).decode('utf-8')
            )
        )['count']) # 1



This example:

1. Downloads Wasm from the web,
2. Verifies that the Wasm matches a hash before running it,
3. And executes a function exported from that module from Python.

Host Functions
--------------

What if you want your guest plugin to communicate with your host? **Extism has
your back.**

Let's take a look at a slightly more advanced example. This time, we're going
to call a guest function in a *locally* defined module in WebAssembly Text
Format (AKA "WAT" format), that *guest* function is going to call a *host* function,
and then the *guest* function will return the result.

Lets take a look at a new example.

.. sourcecode:: python
    :linenos:
    :caption: ``host.py``

    from extism import host_fn, Plugin

    # Our host function. Note the type annotations -- these allow extism to
    # automatically generate Wasm type bindings for the function!
    @host_fn()
    def hello_world(input: str) -> str:
        print(input)
        return "Hello from Python!"

    with Plugin(open("guest.wat", "rb").read()) as plugin:
        plugin.call("my_func", b"")

We've defined a host function that takes a string and returns a string. If
you're interested in the guest plugin code, check it out below.

The :func:`.extism.host_fn` decorator registers our Python function with
``extism``, inferring the name we want to use from the function name. Because
``hello_world`` has type annotations, :func:`.extism.host_fn` automatically
created appropriate low-level Wasm bindings for us. We can take this a step
further, though: if we expect to be called with JSON data, we can indicate
as much:

.. sourcecode:: python
    :linenos:
    :caption: ``host.py``

    from extism import host_fn, Plugin, Json
    from typing import Annotated

    # Our host function. Note the type annotations -- these allow extism to
    # automatically generate Wasm type bindings for the function!
    @host_fn()
    def hello_world(input: Annotated[dict, Json]) -> str:
        print(input['message'])
        return "Hello from Python!"

    with Plugin(open("guest.wat", "rb").read()) as plugin:
        plugin.call("my_func", b"")

.. _guest_code:

Guest Code
~~~~~~~~~~

.. tip:: If the WebAssembly here looks intimidating, check out Extism Plugin Dev Kits
   (PDKs), which allow you to write code in your language of choice.

.. sourcecode:: lisp
    :linenos:
    :caption: guest.wat

    (module
        (; code between winking-emoji parenthesis is a WAT comment! ;)

        (import "env" "hello_world" (func $hello (param i64) (result i64)))
        (import "env" "extism_alloc" (func $extism_alloc (param i64) (result i64)))
        (import "env" "extism_store_u8" (func $extism_store_u8 (param i64 i32)))
        (import "env" "extism_output_set" (func $extism_output_set (param i64 i64)))
        (import "env" "extism_length" (func $extism_length (param i64) (result i64)))

        (; store a string to send to the host. ;)
        (memory $memory (export "mem")
          (data "{\"message\": \"Hello from WAT!\"}\00")
        )
        (func $my_func (result i64)
          (local $result i64)
          (local $offset i64)
          (local $i i32)
          (local.set $offset (call $extism_alloc (i64.const 15)))

          (;
            You can read this as:

            for(i=0; memory[i] != 0; ++i) {
              extism_store_u8(offset + i, memory[i])
            }

            We're copying our local string into extism memory to transport it to the host.
          ;)
          (block $end
            (loop $loop
              (br_if $end (i32.eq (i32.const 0) (i32.load8_u (local.get $i))))

              (call $extism_store_u8
                (i64.add
                  (local.get $offset)
                  (i64.extend_i32_u (local.get $i))
                )
                (i32.load8_u (local.get $i))
              )

              (local.set $i (i32.add (i32.const 1) (local.get $i)))
              br $loop
            )
          )

          (; call the host and store the resulting offset into extism memory in a local variable. ;)
          local.get $offset
          (local.set $result (call $hello (local.get $offset)))

          (;
            now tell extism we want to use that offset as our output memory. extism tracks the extent
            of that memory, so we can call extism_length() to get that data.
          ;)
          (call $extism_output_set
            (local.get $result)
            (call $extism_length (local.get $result))
          )
        )
        (export "my_func" (func $my_func))
    )

