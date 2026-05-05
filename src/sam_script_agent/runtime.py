from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from solace_agent_mesh.agent.utils.artifact_helpers import save_artifact_with_metadata
from solace_agent_mesh.common import a2a
from solace_agent_mesh.common.data_parts import AgentProgressUpdateData, ArtifactRef


@dataclass
class ScriptAgentResult:
    """Normalized result contract for script entrypoints."""

    text: Optional[str] = None
    data: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    mime_type: str = "application/json"
    save_output_as_artifact: bool = True


class ScriptAgentExecutionContext:
    """Context object made available to script entrypoints."""

    def __init__(self, component: Any, a2a_context: Dict[str, Any], invocation_data: Any = None):
        self.component = component
        self.a2a_context = a2a_context
        self.invocation_data = invocation_data

    @property
    def task_id(self) -> str:
        return self.a2a_context["logical_task_id"]

    @property
    def session_id(self) -> str:
        return self.a2a_context["session_id"]

    @property
    def user_id(self) -> str:
        return self.a2a_context["user_id"]

    @property
    def client_id(self) -> Optional[str]:
        return self.a2a_context.get("client_id")

    @property
    def user_config(self) -> Dict[str, Any]:
        return self.a2a_context.get("a2a_user_config", {})

    @property
    def is_structured_invocation(self) -> bool:
        return bool(self.invocation_data)

    async def emit_progress(self, status_text: str, data: Optional[Dict[str, Any]] = None) -> None:
        status_topic = self.a2a_context.get("statusTopic")
        if not status_topic:
            return

        if data is None:
            signal_data = AgentProgressUpdateData(
                type="agent_progress_update",
                status_text=status_text,
            )
            event = a2a.create_data_signal_event(
                task_id=self.task_id,
                context_id=self.session_id,
                signal_data=signal_data,
                agent_name=self.component.agent_name,
            )
        else:
            event_message = a2a.create_agent_data_message(
                data=data,
                task_id=self.task_id,
                context_id=self.session_id,
            )
            event = a2a.create_status_update(
                task_id=self.task_id,
                context_id=self.session_id,
                message=event_message,
                is_final=False,
                metadata={"agent_name": self.component.agent_name},
            )

        response = a2a.create_success_response(
            result=event,
            request_id=self.a2a_context.get("jsonrpc_request_id"),
        )
        self.component.publish_a2a_message(
            payload=response.model_dump(exclude_none=True),
            topic=status_topic,
            user_properties={"a2aUserConfig": self.user_config},
        )

    async def save_output_artifact(
        self,
        payload: Any,
        filename: Optional[str] = None,
        mime_type: str = "application/json",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef:
        if not self.component.artifact_service:
            raise ValueError("Artifact service is not configured for this script agent.")

        if filename is None:
            if self.invocation_data and self.invocation_data.suggested_output_filename:
                filename = self.invocation_data.suggested_output_filename
            else:
                filename = f"{self.component.agent_name}_{self.task_id[-8:]}_result.json"

        if isinstance(payload, bytes):
            content_bytes = payload
        elif mime_type == "application/json":
            content_bytes = json.dumps(payload).encode("utf-8")
        else:
            content_bytes = str(payload).encode("utf-8")

        save_result = await save_artifact_with_metadata(
            artifact_service=self.component.artifact_service,
            app_name=self.component.agent_name,
            user_id=self.user_id,
            session_id=self.session_id,
            filename=filename,
            content_bytes=content_bytes,
            mime_type=mime_type,
            metadata_dict=metadata or {},
            timestamp=datetime.now(timezone.utc),
            tags=["working"],
        )
        if save_result.get("status") != "success":
            raise RuntimeError(save_result.get("message", "Failed to save artifact"))
        return ArtifactRef(name=filename, version=save_result.get("data_version"))
