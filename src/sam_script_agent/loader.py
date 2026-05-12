from __future__ import annotations

import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict

from .config import ScriptHandlerConfig

log = logging.getLogger(__name__)


class ScriptLoader:
    """Loads and invokes Python script entrypoints."""

    def __init__(self, config: ScriptHandlerConfig):
        self.config = config
        self._callable = self._load_callable()

    @property
    def handler(self) -> Callable[..., Any]:
        return self._callable

    def _load_callable(self) -> Callable[..., Any]:
        module = self._import_module()
        func = getattr(module, self.config.function_name, None)
        if not callable(func):
            raise ValueError(
                f"Function '{self.config.function_name}' not found in module "
                f"'{self.config.component_module}'."
            )
        return func

    def _import_module(self):
        module_name = self.config.component_module

        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            pass

        base_path = str(Path(self.config.component_base_path).resolve())
        if base_path not in sys.path:
            sys.path.insert(0, base_path)
            log.debug("Added '%s' to sys.path for module '%s'", base_path, module_name)

        return importlib.import_module(module_name)

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
