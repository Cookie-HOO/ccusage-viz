from __future__ import annotations

import argparse
import os
import sys

from ccusage_viz import __version__
from ccusage_viz.application import run
from ccusage_viz.cli.configuration import _route, _to_options, _validate_configuration
from ccusage_viz.cli.routing import (
    ShortCircuitKind,
    ShortCircuitRoute,
    _inject_default_command,
    _top_level_typo,
    probe_short_circuit,
)
from ccusage_viz.command_parsing.common import _explicit_fields
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.i18n import detect_language, load_translator


def _render_short_circuit(route: ShortCircuitRoute) -> int:
    if route.kind is ShortCircuitKind.VERSION:
        print(f"ccusage-viz {__version__}")
        return 0
    tr = load_translator(route.language or detect_language())
    parser = build_parser(tr)
    parser.parse_args(route.command.split() + ["--help"] if route.command else ["--help"])
    raise AssertionError("argparse help did not exit")


def _preparse_language(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lang", choices=("en", "zh"))
    namespace, _ = parser.parse_known_args(argv)
    return namespace.lang or detect_language()


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    launcher = os.environ.get("CCUV_LAUNCHER") or "ccuv"
    short_circuit = probe_short_circuit(raw_args)
    if short_circuit is not None:
        return _render_short_circuit(short_circuit)
    args = _inject_default_command(raw_args)
    explicit = _explicit_fields(args)
    language = _preparse_language(args)
    tr = load_translator(language)
    try:
        parser = build_parser(tr)
        try:
            namespace = parser.parse_args(args)
        except UsageError as error:
            enriched = _top_level_typo(raw_args, error)
            if enriched is error:
                raise
            raise enriched from error
        if hasattr(namespace, "lang") and namespace.lang is None:
            namespace.lang = language
        if namespace.command == "dataset":
            from ccusage_viz.datasets.manager_rendering import format_dataset_list
            from ccusage_viz.datasets.manager_runtime import run_dataset_manager
            from ccusage_viz.datasets.service import DatasetService

            service = DatasetService()
            if namespace.dataset_command == "list":
                print(format_dataset_list(service.registrations(), tr))
                return 0
            if namespace.dataset_command == "add-local":
                if not namespace.command_argv:
                    raise UsageError(
                        "error.arguments", detail="dataset add-local requires a command"
                    )
                result = service.register_local_command(tuple(namespace.command_argv), replace=True)
                print(result.registration.dataset_id)
                return 0
            return run_dataset_manager(service, tr)
        if namespace.command == "text":
            from ccusage_viz.clock_overlay import describe_time_state, render_time_state

            if namespace.preset == "time-state":
                if namespace.text_mode == "describe":
                    print(describe_time_state(namespace.lang or language))
                else:
                    print(render_time_state(namespace.lang or language))
                return 0
            raise AssertionError("unsupported text preset")
        options = _to_options(namespace, explicit=explicit, launcher=launcher)
        _validate_configuration(options)
        route = _route(options)
        route_language = getattr(route.launch, "language", None)
        return run(route.launch, load_translator(route_language) if route_language else tr)
    except VizError as exc:
        text = format_error(
            exc,
            tr,
            color=color_enabled(
                sys.stderr,
                no_color=getattr(locals().get("namespace"), "color_scheme", "classic")
                == "no-color",
            ),
            color_scheme=getattr(locals().get("namespace"), "color_scheme", "classic"),
        )
        print(text, file=sys.stderr)
        return exc.exit_code
