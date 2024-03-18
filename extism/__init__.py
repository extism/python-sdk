"""
The extism python SDK, used for embedding guest Wasm programs into python
hosts.
"""

from .extism import (
    Error,
    Plugin,
    set_log_file,
    set_log_custom,
    extism_version,
    host_fn,
    Function,
    Memory,
    ValType,
    Val,
    CurrentPlugin,
    Codec,
    Json,
    Pickle,
)

from .pool import (
    Pool,
    PoolPlugin
)

__all__ = [
    "Plugin",
    "Error",
    "CurrentPlugin",
    "set_log_file",
    "set_log_custom",
    "extism_version",
    "Memory",
    "host_fn",
    "CurrentPlugin",
    "Function",
    "ValType",
    "Val",
    "Codec",
    "Json",
    "Pickle",
    "Pool",
    "PoolPlugin",
]
