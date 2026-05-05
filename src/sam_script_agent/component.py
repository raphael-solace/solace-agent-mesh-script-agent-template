from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from a2a.types import A2ARequest, AgentCapabilities, AgentCard, AgentExtension, TaskState
from solace_ai_connector.common.message import Message as SolaceMessage

from solace_agent_mesh.agent.adk.services import (
    initialize_artifact_service,
    initialize_session_service,
)
from solace_agent_mesh.common import a2a
from solace_agent_mesh.common.constants import EXTENSION_URI_SCHEMAS

DISPLAY_NAME_EXTENSION_URI = "https://solace.com/a2a/extensions/display-name"
from solace_agent_mesh.common.data_parts import StructuredInvocationRequest, StructuredInvocationResult
from solace_agent_mesh.common.sac.sam_component_base import SamComponentBase

from .config import ScriptAgentAppConfig
from .loader import ScriptLoader
from .runtime import ScriptAgentExecutionContext, ScriptAgentResult

log = logging.getLogger(__name__)

info = {
    "class_name": "ScriptAgentComponent",
    "description": "Pure-Python script-backed SAM agent.",
    "config_parameters": [],
}


class ScriptAgentComponent(SamComponentBase):
    """A pure-Python SAM component that behaves like an agent."""

    HOST_COMPONENT_VERSION = "0.1.0"

    def __init__(self, **kwargs: Any):
        raw_app_config = kwargs.get("config", {}).get("component_config", {}).get("app_config", {})
        agent_name = raw_app_config.get("agent_name")
        if agent_name:
            kwargs.setdefault("name", agent_name)

        super().__init__(info, **kwargs)

        self.agent_name = self.get_config("agent_name")
        self.namespace = self.get_config("namespace")
        self.auto_summarization_config = self.get_config(
            "auto_summarization", {"enabled": False, "compaction_percentage": 0.25}
        )
        self.app_config = ScriptAgentAppConfig.model_validate_and_clean(raw_app_config)
        self.loader = ScriptLoader(self.app_config.script)
        self.session_service = initialize_session_service(self)
        self.artifact_service = initialize_artifact_service(self)

    def invoke(self, message: SolaceMessage, data: dict) -> dict:
        return None

    def _get_component_id(self) -> str:
        return self.agent_name

    def _get_component_type(self) -> str:
        return "agent"

    async def _handle_message_async(self, message: SolaceMessage, topic: str) -> None:
        request_topic = a2a.get_agent_request_topic(self.namespace, self.agent_name)
        discovery_topic = a2a.get_discovery_subscription_topic(self.namespace)

        if topic == request_topic:
            try:
                await self._handle_request(message)
            except Exception as exc:
                log.exception("%s Unhandled script-agent request error: %s", self.log_identifier, exc)
                await self._publish_terminal_failure(message, None, None, str(exc))
        elif a2a.topic_matches_subscription(topic, discovery_topic):
            message.call_acknowledgements()
        else:
            log.warning("%s Unknown topic: %s", self.log_identifier, topic)
            message.call_acknowledgements()

    async def _async_setup_and_run(self) -> None:
        await super()._async_setup_and_run()
        self._setup_periodic_agent_card_publishing()
        log.info("%s Script agent ready: %s", self.log_identifier, self.agent_name)

    def _pre_async_cleanup(self) -> None:
        pass

    def _setup_periodic_agent_card_publishing(self) -> None:
        publish_config = self.get_config("agent_card_publishing", {})
        interval_seconds = publish_config.get("interval_seconds")
        if not interval_seconds or interval_seconds <= 0:
            return
        self._publish_agent_card_sync()
        self.add_timer(
            delay_ms=interval_seconds * 1000,
            timer_id="script_agent_card_publish",
            interval_ms=interval_seconds * 1000,
            callback=lambda timer_data: self._publish_agent_card_sync(),
        )

    def _create_agent_card(self) -> AgentCard:
        card_config = self.get_config("agent_card", {})
        extensions = []

        input_schema = self.get_config("input_schema")
        output_schema = self.get_config("output_schema")
        display_name = self.get_config("display_name")
        if display_name:
            extensions.append(
                AgentExtension(
                    uri=DISPLAY_NAME_EXTENSION_URI,
                    description="Friendly display name for the script agent.",
                    params={"display_name": display_name},
                )
            )

        if input_schema or output_schema:
            schema_params: Dict[str, Any] = {}
            if input_schema:
                schema_params["input_schema"] = input_schema
            if output_schema:
                schema_params["output_schema"] = output_schema
            extensions.append(
                AgentExtension(
                    uri=EXTENSION_URI_SCHEMAS,
                    description="Input and output JSON schemas for the script agent.",
                    params=schema_params,
                )
            )

        return AgentCard(
            name=self.agent_name,
            description=card_config.get("description", ""),
            defaultInputModes=card_config.get("defaultInputModes", ["text"]),
            defaultOutputModes=card_config.get("defaultOutputModes", ["text"]),
            skills=card_config.get("skills", []),
            capabilities=AgentCapabilities(
                streaming=False,
                extensions=extensions or None,
            ),
            version=self.HOST_COMPONENT_VERSION,
            url=f"solace:{a2a.get_agent_request_topic(self.namespace, self.agent_name)}",
        )

    def _publish_agent_card_sync(self) -> None:
        agent_card = self._create_agent_card()
        discovery_topic = a2a.get_agent_discovery_topic(self.namespace)
        self.publish_a2a_message(
            payload=agent_card.model_dump(exclude_none=True),
            topic=discovery_topic,
        )

    async def _handle_request(self, message: SolaceMessage) -> None:
        payload = message.get_payload()
        if not isinstance(payload, dict):
            raise ValueError("Payload is not a dictionary")

        request = A2ARequest.model_validate(payload)
        method = a2a.get_request_method(request)
        if method == "tasks/cancel":
            await self._handle_cancel(message, request)
            return
        if method not in {"message/send", "message/stream"}:
            raise ValueError(f"Unsupported A2A method: {method}")

        a2a_message = a2a.get_message_from_send_request(request)
        if a2a_message is None:
            raise ValueError("A2A request does not contain a message")

        invocation_data = self._extract_structured_invocation_request(a2a_message)
        input_data = await self._extract_input_data(a2a_message)
        a2a_context = self._build_a2a_context(message, request, a2a_message, invocation_data)
        context = ScriptAgentExecutionContext(self, a2a_context, invocation_data)

        await context.emit_progress("Script execution started")

        try:
            result = await asyncio.wait_for(
                self.loader.invoke(input_data=input_data, context=context),
                timeout=self.app_config.script.execution_timeout_seconds,
            )
            normalized = self._normalize_result(result)
            await self._publish_success(
                message=message,
                a2a_context=a2a_context,
                invocation_data=invocation_data,
                result=normalized,
            )
        except Exception as exc:
            await self._publish_failure(
                message=message,
                a2a_context=a2a_context,
                invocation_data=invocation_data,
                error_message=str(exc),
            )

    def _build_a2a_context(
        self,
        message: SolaceMessage,
        request: A2ARequest,
        a2a_message: Any,
        invocation_data: Optional[StructuredInvocationRequest],
    ) -> Dict[str, Any]:
        user_properties = message.get_user_properties()
        return {
            "logical_task_id": str(a2a.get_request_id(request)),
            "session_id": a2a_message.context_id,
            "user_id": user_properties.get("userId", "default_user"),
            "client_id": user_properties.get("clientId"),
            "jsonrpc_request_id": a2a.get_request_id(request),
            "replyToTopic": user_properties.get("replyTo"),
            "statusTopic": user_properties.get("a2aStatusTopic"),
            "a2a_user_config": user_properties.get("a2aUserConfig", {}),
            "call_depth": int(user_properties.get("callDepth", 0) or 0),
            "is_structured_invocation": bool(invocation_data),
        }

    def _extract_structured_invocation_request(self, a2a_message: Any) -> Optional[StructuredInvocationRequest]:
        for part in a2a.get_data_parts_from_message(a2a_message):
            if isinstance(part.data, dict) and part.data.get("type") == "structured_invocation_request":
                return StructuredInvocationRequest.model_validate(part.data)
        return None

    async def _extract_input_data(self, a2a_message: Any) -> Dict[str, Any]:
        from solace_agent_mesh.agent.utils.artifact_helpers import parse_artifact_uri

        for file_part in a2a.get_file_parts_from_message(a2a_message):
            uri = a2a.get_uri_from_file_part(file_part)
            if uri and uri.startswith("artifact://"):
                uri_parts = parse_artifact_uri(uri)
                artifact = await self.artifact_service.load_artifact(
                    app_name=uri_parts["app_name"],
                    user_id=uri_parts["user_id"],
                    session_id=uri_parts["session_id"],
                    filename=uri_parts["filename"],
                    version=uri_parts["version"],
                )
                if artifact and artifact.inline_data:
                    return json.loads(artifact.inline_data.data.decode("utf-8"))

        data_parts = a2a.get_data_parts_from_message(a2a_message)
        for data_part in data_parts:
            if isinstance(data_part.data, dict) and data_part.data.get("type") == "structured_invocation_request":
                continue
            return data_part.data

        text = a2a.get_text_from_message(a2a_message)
        if text:
            return {"text": text}
        return {}

    def _normalize_result(self, value: Any) -> ScriptAgentResult:
        if isinstance(value, ScriptAgentResult):
            return value
        if isinstance(value, str):
            return ScriptAgentResult(text=value, data={"text": value}, mime_type="text/plain")
        if isinstance(value, (dict, list, int, float, bool)) or value is None:
            return ScriptAgentResult(data=value)
        return ScriptAgentResult(text=str(value), data={"value": str(value)})

    async def _publish_success(
        self,
        message: SolaceMessage,
        a2a_context: Dict[str, Any],
        invocation_data: Optional[StructuredInvocationRequest],
        result: ScriptAgentResult,
    ) -> None:
        result_data_part = None
        output_artifact_ref = None
        if invocation_data and self.app_config.script.auto_save_structured_output:
            output_artifact_ref = await ScriptAgentExecutionContext(
                self, a2a_context, invocation_data
            ).save_output_artifact(
                payload=result.data if result.data is not None else {"text": result.text},
                mime_type=result.mime_type,
                metadata={
                    "source": "script_agent",
                    "agent_name": self.agent_name,
                    "workflow_name": invocation_data.workflow_name,
                    "node_id": invocation_data.node_id,
                },
            )
            result_data_part = StructuredInvocationResult(
                type="structured_invocation_result",
                status="success",
                output_artifact_ref=output_artifact_ref,
            )

        parts = []
        if result_data_part is not None:
            parts.append(a2a.create_data_part(data=result_data_part.model_dump()))
        elif result.data is not None:
            parts.append(a2a.create_data_part(data={"type": "script_result", "data": result.data}))

        text = result.text
        if invocation_data is None and result.data is not None:
            if isinstance(result.data, str):
                text = result.data
            else:
                text = json.dumps(result.data)
        elif text is None:
            if result.data is None:
                text = "Script completed successfully."
            elif isinstance(result.data, str):
                text = result.data
            else:
                text = json.dumps(result.data)
        parts.append(a2a.create_text_part(text=text))

        final_task = a2a.create_final_task(
            task_id=a2a_context["logical_task_id"],
            context_id=a2a_context["session_id"],
            final_status=a2a.create_task_status(
                state=TaskState.completed,
                message=a2a.create_agent_parts_message(
                    parts=parts,
                    task_id=a2a_context["logical_task_id"],
                    context_id=a2a_context["session_id"],
                    metadata=result.metadata or None,
                ),
            ),
            metadata={
                "agent_name": self.agent_name,
                "output": result.data,
            },
        )

        response_topic = a2a_context.get("replyToTopic") or a2a.get_client_response_topic(
            self.namespace, a2a_context["client_id"]
        )
        response = a2a.create_success_response(
            result=final_task,
            request_id=a2a_context["jsonrpc_request_id"],
        )
        self.publish_a2a_message(
            payload=response.model_dump(exclude_none=True),
            topic=response_topic,
            user_properties={"a2aUserConfig": a2a_context.get("a2a_user_config", {})},
        )
        message.call_acknowledgements()

    async def _publish_failure(
        self,
        message: SolaceMessage,
        a2a_context: Dict[str, Any],
        invocation_data: Optional[StructuredInvocationRequest],
        error_message: str,
    ) -> None:
        parts = []
        if invocation_data:
            parts.append(
                a2a.create_data_part(
                    data=StructuredInvocationResult(
                        type="structured_invocation_result",
                        status="error",
                        error_message=error_message,
                    ).model_dump()
                )
            )
        parts.append(a2a.create_text_part(text=f"Script failed: {error_message}"))

        final_task = a2a.create_final_task(
            task_id=a2a_context["logical_task_id"],
            context_id=a2a_context["session_id"],
            final_status=a2a.create_task_status(
                state=TaskState.failed,
                message=a2a.create_agent_parts_message(
                    parts=parts,
                    task_id=a2a_context["logical_task_id"],
                    context_id=a2a_context["session_id"],
                ),
            ),
            metadata={"agent_name": self.agent_name},
        )
        response_topic = a2a_context.get("replyToTopic") or a2a.get_client_response_topic(
            self.namespace, a2a_context["client_id"]
        )
        response = a2a.create_success_response(
            result=final_task,
            request_id=a2a_context["jsonrpc_request_id"],
        )
        self.publish_a2a_message(
            payload=response.model_dump(exclude_none=True),
            topic=response_topic,
            user_properties={"a2aUserConfig": a2a_context.get("a2a_user_config", {})},
        )
        message.call_acknowledgements()

    async def _publish_terminal_failure(
        self,
        message: SolaceMessage,
        request_id: Optional[str],
        reply_to_topic: Optional[str],
        error_message: str,
    ) -> None:
        if reply_to_topic and request_id is not None:
            error_response = a2a.create_internal_error_response(
                message=error_message,
                request_id=request_id,
            )
            self.publish_a2a_message(
                payload=error_response.model_dump(exclude_none=True),
                topic=reply_to_topic,
            )
        message.call_acknowledgements()

    async def _handle_cancel(self, message: SolaceMessage, request: A2ARequest) -> None:
        task_id = a2a.get_task_id_from_cancel_request(request)
        reply_to_topic = message.get_user_properties().get("replyTo")
        if not reply_to_topic:
            message.call_acknowledgements()
            return

        final_task = a2a.create_final_task(
            task_id=task_id,
            context_id=task_id,
            final_status=a2a.create_task_status(
                state=TaskState.canceled,
                message=a2a.create_agent_parts_message(
                    parts=[a2a.create_text_part(text="Script task was cancelled.")],
                    task_id=task_id,
                    context_id=task_id,
                ),
            ),
            metadata={"agent_name": self.agent_name},
        )
        response = a2a.create_success_response(
            result=final_task,
            request_id=a2a.get_request_id(request),
        )
        self.publish_a2a_message(
            payload=response.model_dump(exclude_none=True),
            topic=reply_to_topic,
            user_properties={"a2aUserConfig": message.get_user_properties().get("a2aUserConfig", {})},
        )
        message.call_acknowledgements()
