from typing import Optional, Union, Dict, List, Callable
from threading import Thread, Lock
import time
import asyncio

from .extism import Plugin

class PoolPlugin:
    plugin: Plugin
    active: bool

    def __init__(self, plugin: Plugin, active=False):
        self.plugin = plugin
        self.active = active

    def make_active(self, active=True):
        self.active = active
        return self

    def call(self, *args, **kw):
        return self.plugin.call(*args, **kw)

    def __enter__(self):
        return self.make_active()

    def __exit__(self, *args):
        self.active = False

class PoolError(Exception):
    pass

class Pool:
    plugins: Dict[str, Callable[[], Plugin]]
    instances: Dict[str, List[PoolPlugin]]

    def __init__(self, max_instances=1):
        self.max_instances = max_instances
        self.instances = {}
        self.plugins = {}
        self.count = {}

    def add(self, name, source: Callable[[], Plugin]):
        self.plugins[name] = source
        self.instances[name] = []

    def find_available(self, name):
        entry = self.instances[name]
        for instance in entry:
            if not instance.active:
                return instance.make_active()
        return None

    async def async_get(self, name, timeout=None):
        start = time.time()
        entry = self.instances[name]

        p = self.find_available(name)
        if p is not None:
            return p
        
        if len(entry) < self.max_instances:
            p = PoolPlugin(self.plugins[name](), active=True)
            entry.append(p)
            self.instances[name] = entry
            return p

        while True:
            p = self.find_available(name)
            if p is not None:
                return p
            else:
                if timeout is None:
                    await asyncio.sleep(0)
                    continue
                elif (time.time() - start) >= timeout:
                    raise PoolError("Timed out getting instance for key " + name)

    def get(self, name, timeout=None):
        fut = self.async_get(name, timeout) 
        try:
            if asyncio.get_event_loop().is_running:
                return fut
            else:
                return asyncio.run(fut)
        except:
            return asyncio.run(fut)

