import os

_search_dirs = ["/usr/local", "/usr", os.path.join(os.getenv("HOME"), ".local"), "."]


class Error(Exception):
    """Extism error type"""

    pass


def _check_for_header_and_lib(p):
    def _exists(a, *b):
        return os.path.exists(os.path.join(a, *b))

    if _exists(p, "extism.h"):
        if _exists(p, "libextism.so"):
            return os.path.join(p, "extism.h"), os.path.join(p, "libextism.so")

        if _exists(p, "libextism.dylib"):
            return os.path.join(p, "extism.h"), os.path.join(p, "libextism.dylib")

    if _exists(p, "include", "extism.h"):
        if _exists(p, "lib", "libextism.so"):
            return os.path.join(p, "include", "extism.h"), os.path.join(
                p, "lib", "libextism.so"
            )

        if _exists(p, "lib", "libextism.dylib"):
            return os.path.join(p, "include", "extism.h"), os.path.join(
                p, "lib", "libextism.dylib"
            )


def _locate():
    """Locate extism library and header"""
    script_dir = os.path.dirname(__file__)
    env = os.getenv("EXTISM_PATH")
    if env is not None:
        r = _check_for_header_and_lib(env)
        if r is not None:
            return r

    r = _check_for_header_and_lib(script_dir)
    if r is not None:
        return r

    r = _check_for_header_and_lib(".")
    if r is not None:
        return r

    for d in _search_dirs:
        r = _check_for_header_and_lib(d)
        if r is not None:
            return r

    raise Error("Unable to locate the extism library and header file")


if __name__ == "__main__":
    print(_locate())
