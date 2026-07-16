"""Command boundary for running report generation."""

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .errors import HarnessError, CommandError
from .evidence import ImageEvidenceResolver
from .pipeline import ReportRunner
from .providers import GitHubCopilotProvider, OpenAICompatibleProvider
from .workbook import ExcelWorkbook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-harness",
        description="Generate report answers and justifications from image evidence.",
    )
    parser.add_argument("workbook", type=Path, help="Input Excel workbook")
    parser.add_argument(
        "--provider",
        choices=("openai-compatible", "github-copilot"),
        required=True,
        help="Provider entry point to use",
    )
    parser.add_argument("--output", type=Path, help="Output workbook path")
    parser.add_argument("--sheet", help="Worksheet name; defaults to the active sheet")
    parser.add_argument(
        "--evidence-base-dir",
        type=Path,
        help="Directory for relative image references; defaults to the workbook directory",
    )
    parser.add_argument("--instructions", default="", help="Instructions sent with each image")
    parser.add_argument("--model", default="gpt-4o", help="Provider model name")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument("--copilot-token", help="GitHub Copilot login token")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        provider = _build_provider(args)
        workbook = ExcelWorkbook(args.workbook, sheet_name=args.sheet)
        evidence = ImageEvidenceResolver(
            base_dir=args.evidence_base_dir or args.workbook.parent
        )
        ReportRunner(
            workbook=workbook,
            evidence=evidence,
            provider=provider,
            instructions=args.instructions,
        ).run(args.output)
    except (HarnessError, OSError, ValueError) as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 1
    return 0


def _build_provider(args: argparse.Namespace):
    if args.provider == "openai-compatible":
        if not args.base_url:
            raise CommandError(
                "OpenAI-compatible provider requires --base-url"
            )
        api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise CommandError(
                "OpenAI-compatible provider requires --api-key or OPENAI_API_KEY"
            )
        return OpenAICompatibleProvider(
            base_url=args.base_url,
            api_key=api_key,
            model=args.model,
        )
    return GitHubCopilotProvider(token=args.copilot_token, model=args.model)
