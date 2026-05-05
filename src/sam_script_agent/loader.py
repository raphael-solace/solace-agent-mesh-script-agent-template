from __future__ import annotations

import importlib
import inspect
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator

from .config import ScriptHandlerConfig


@contextmanager
def _temporary_sys_path(path: str) -> Iterator[None]:
    resolved = str(Path(path).resolve())
    inserted = False
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
        inserted = True
    try:
        yield
    finally:
        if inserted and resolved in sys.path:
            sys.path.remove(resolved)


class ScriptLoader:
    """Loads and invokes Python script entrypoints."""

    def __init__(self, config: ScriptHandlerConfig):
        self.config = config
        self._callable = self._load_callable()

    @property
    def handler(self) -> Callable[..., Any]:
        return self._callable

    def _load_callable(self) -> Callable[..., Any]:
        with _temporary_sys_path(self.config.component_base_path):
            module = importlib.import_module(self.config.component_module)
        func = getattr(module, self.config.function_name, None)
        if not callable(func):
            raise ValueError(
                f"Function '{self.config.function_name}' not found in module "
                f"'{self.config.component_module}'."
            )
        return func

    async def invoke(self, input_data: Dict[str, Any], context: Any) -> Any:
        kwargs = self._build_kwargs(input_data, context)
        result = self.handler(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _build_kwargs(self, input_data: Dict[str, Any], context: Any) -> Dict[str, Any]:
        mode = self.config.input_mode
        if mode == "input_data":
            return {"input_data": input_data, "context": context}

        signature = inspect.signature(self.handler)
        params = signature.parameters
        kwargs: Dict[str, Any] = {}
        remaining = dict(input_data)

        if "context" in params:
            kwargs["context"] = context
        if "input_data" in params:
            kwargs["input_data"] = input_data
            if mode == "smart":
                return kwargs

        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

        for name, param in params.items():
            if name in kwargs:
                continue
            if name in remaining:
                kwargs[name] = remaining.pop(name)
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                continue

        if has_var_keyword:
            kwargs.update(remaining)
        elif mode == "kwargs" and remaining:
            unknown = ", ".join(sorted(remaining))
            raise ValueError(
                f"Input contains keys that do not match the script signature: {unknown}"
            )

        return kwargs
