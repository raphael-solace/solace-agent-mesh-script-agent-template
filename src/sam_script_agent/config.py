from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import Field, model_validator

from solace_agent_mesh.agent.sac.app import (
    AgentCardConfig,
    AgentCardPublishingConfig,
    SamAgentAppConfig,
)
from solace_agent_mesh.common.utils.pydantic_utils import SamConfigBase


class ScriptHandlerConfig(SamConfigBase):
    """Configuration describing which Python function to execute."""

    component_module: str = Field(
        ...,
        description="Python module that contains the script entrypoint.",
    )
    component_base_path: str = Field(
        default=".",
        description="Filesystem base path added to sys.path before import.",
    )
    function_name: str = Field(
        default="run",
        description="Function name within component_module to execute.",
    )
    input_mode: Literal["smart", "kwargs", "input_data"] = Field(
        default="smart",
        description="How input data is mapped onto the script function signature.",
    )
    execution_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Maximum time allowed for a single script execution.",
    )
    auto_save_structured_output: bool = Field(
        default=True,
        description="When true, structured invocations save result payloads as artifacts automatically.",
    )


class ScriptAgentAppConfig(SamAgentAppConfig):
    """App config for a script-backed SAM agent."""

    agent_type: Literal["script"] = "script"
    script: ScriptHandlerConfig = Field(
        ...,
        description="Python script entrypoint configuration.",
    )
    model: Optional[Union[str, Dict[str, Any]]] = None
    instruction: Optional[Any] = None
    agent_card: AgentCardConfig = Field(
        default_factory=AgentCardConfig,
        description="Static definition of this script agent's capabilities for discovery.",
    )
    agent_card_publishing: AgentCardPublishingConfig = Field(
        default_factory=lambda: AgentCardPublishingConfig(interval_seconds=10),
        description="Settings for publishing the agent card.",
    )

    @model_validator(mode="after")
    def _validate_model_requirement(self) -> "ScriptAgentAppConfig":
        """Override SAM's model requirement for pure script agents."""
        return self
