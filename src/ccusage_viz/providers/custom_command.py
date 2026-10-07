from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from threading import Event

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.custom_protocol import (
    CustomProbeRequest,
    V2ProbeRequest,
    CustomProtocolError,
    CustomRequest,
    canonical_custom_request_key,
    parse_custom_response,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage import _communicate_bounded, _decode_stderr
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResult,
    ProviderResultFragment,
    QueryIntent,
)
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition

CUSTOM_COMMAND_PROVIDER = ProviderRef("custom-command")


@dataclass(frozen=True, slots=True)
class CustomCommandProvider:
    """Execute one self-describing custom command request per physical query."""

    provider = CUSTOM_COMMAND_PROVIDER
    capabilities = ProviderCapabilities(
        resolutions=(DataResolution.DATE.value,),
        dimensions=(),
        execution_options=(),
    )

    def compile(self, intent: QueryIntent) -> PhysicalPlan:
        if intent.provider.provider_id != self.provider.provider_id:
            raise ValueError("custom-command provider cannot compile another provider's intent")
        self.capabilities.validate(intent)
        custom_request = intent.payload
        if not isinstance(custom_request, CustomRequest):
            raise ValueError("custom-command intent requires a custom request")
        if (
            not isinstance(custom_request, (CustomProbeRequest, V2ProbeRequest))
            and intent.provider.source_id != custom_request.dataset_id
        ):
            raise ValueError("custom-command provider source must match request dataset")
        arguments = tuple(
            json.dumps(value, separators=(",", ":"), ensure_ascii=True)
            for value in canonical_custom_request_key(custom_request)
        )
        coverage = DateCoverage(intent.missing_intervals)
        query = PhysicalQuery(
            intent.provider,
            "custom_command",
            arguments,
            intent.execution_context,
            coverage,
            payload=custom_request,
        )
        return PhysicalPlan(intent.fingerprint, (query,))

    def fingerprint(self, query: PhysicalQuery) -> str:
        if query.provider.provider_id != self.provider.provider_id:
            raise ValueError("custom-command provider cannot fingerprint another provider's query")
        return query.fingerprint

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        request = query.payload
        if not isinstance(request, CustomRequest):
            raise ValueError("custom command physical query requires a request payload")
        context = query.execution_context
        if context is None:
            raise ValueError("custom command physical query requires an execution context")
        environment = os.environ.copy()
        environment.update(context.environment)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                list(request.command_argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name == "posix",
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                env=environment,
            )
            assert process.stdin is not None
            try:
                process.stdin.write(request.to_json_bytes())
                process.stdin.close()
            except BrokenPipeError:
                pass
            stdout, stderr = _communicate_bounded(
                process,
                context.output_limit,
                context.timeout,
                cancelled,
                query.operation,
            )
        except FileNotFoundError as exc:
            raise QueryError(
                "error.custom_command_missing", command=request.command_argv[0]
            ) from exc
        except OSError as exc:
            raise QueryError("error.custom_command_start", detail=str(exc)) from exc
        if process.returncode != 0:
            raise QueryError(
                "error.custom_command_failed",
                code=process.returncode,
                stderr=_decode_stderr(stderr),
            )
        if len(stdout) > context.output_limit:
            raise QueryError(
                "error.custom_command_output_limit",
                limit=context.output_limit,
            )
        return PhysicalResult(query, stdout, stderr)

    def normalize(self, result: PhysicalResult) -> ProviderResultFragment:
        request = result.query.payload
        if not isinstance(request, CustomRequest):
            raise ValueError("custom command result lacks its request payload")
        try:
            response = parse_custom_response(result.payload, request)
        except CustomProtocolError as exc:
            raise QueryError(
                "error.custom_command_protocol",
                detail=str(exc),
                stderr=_decode_stderr(result.diagnostics),
                custom_failure=exc.failure,
            ) from exc
        except ValueError as exc:
            raise QueryError(
                "error.custom_command_protocol",
                detail=str(exc),
                stderr=_decode_stderr(result.diagnostics),
            ) from exc
        return ProviderResultFragment(
            (),
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            result.query.coverage,
            custom_response=response,
            diagnostics=result.diagnostics,
        )

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult:
        if len(fragments) != 1 or fragments[0].custom_response is None:
            raise ValueError("custom command plan must assemble exactly one response")
        fragment = fragments[0]
        return ProviderResult(
            (),
            fragment.provenance,
            DataResolution.DATE,
            fragment.coverage,
            custom_response=fragment.custom_response,
            diagnostics=fragment.diagnostics,
        )


CUSTOM_COMMAND_DEFINITION = ProviderDefinition(CustomCommandProvider())
