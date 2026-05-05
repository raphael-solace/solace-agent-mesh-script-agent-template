from __future__ import annotations

import logging
from typing import Any, Dict

from pydantic import ValidationError

from solace_agent_mesh.common.a2a.protocol import (
    get_agent_discovery_topic,
    get_agent_request_topic,
)
from solace_agent_mesh.common.app_base import SamAppBase

from .component import ScriptAgentComponent
from .config import ScriptAgentAppConfig

log = logging.getLogger(__name__)

info = {
    "class_name": "ScriptAgentApp",
    "description": "Custom App class for a pure-Python script-backed SAM agent.",
}


class ScriptAgentApp(SamAppBase):
    """Custom SAM app that hosts one pure-Python script agent component."""

    app_schema = {}

    def __init__(self, app_info: Dict[str, Any], **kwargs: Any):
        app_config_dict = app_info.get("app_config", {})

        agent_name = app_config_dict.get("agent_name", "")
        if not all(c.isalnum() or c == "_" for c in agent_name):
            valid_agent_name = "".join(c if c.isalnum() or c == "_" else "_" for c in agent_name)
            log.warning(
                "Agent name '%s' contains invalid characters. Converted to '%s'",
                agent_name,
                valid_agent_name,
            )
            app_config_dict["agent_name"] = valid_agent_name

        try:
            app_config = ScriptAgentAppConfig.model_validate_and_clean(app_config_dict)
            app_info["app_config"] = app_config
        except ValidationError as exc:
            message = ScriptAgentAppConfig.format_validation_error_message(
                exc, app_info.get("name"), app_config_dict.get("agent_name")
            )
            log.error("Invalid Script Agent configuration:\n%s", message)
            raise

        namespace = app_config.get("namespace")
        agent_name = app_config.get("agent_name")
        broker_request_response = app_info.get("broker_request_response")

        generated_subs = [
            {"topic": get_agent_request_topic(namespace, agent_name)},
            {"topic": get_agent_discovery_topic(namespace)},
        ]

        component_definition = {
            "name": f"{agent_name}_script_host",
            "component_class": ScriptAgentComponent,
            "component_config": {
                "component_name": f"{agent_name}_script_host",
                "app_config": app_config.model_dump(exclude_none=True),
            },
            "subscriptions": generated_subs,
        }
        if broker_request_response:
            component_definition["broker_request_response"] = broker_request_response

        app_info["components"] = [component_definition]

        broker_config = app_info.setdefault("broker", {})
        broker_config["input_enabled"] = True
        broker_config["output_enabled"] = True
        broker_config["queue_name"] = f"{namespace.strip('/')}/q/a2a/{agent_name}"
        broker_config["temporary_queue"] = app_info.get("broker", {}).get("temporary_queue", True)

        super().__init__(app_info, **kwargs)

    def run(self):
        try:
            super().run()
        except Exception as exc:
            log.critical("Failed to start script agent application '%s': %s", self.name, exc, exc_info=exc)
            raise

    def get_component(self, component_name: str | None = None) -> ScriptAgentComponent | None:
        if self.flows and self.flows[0].component_groups:
            for group in self.flows[0].component_groups:
                for component_wrapper in group:
                    component = (
                        component_wrapper.component
                        if hasattr(component_wrapper, "component")
                        else component_wrapper
                    )
                    if isinstance(component, ScriptAgentComponent):
                        return component
        return None
