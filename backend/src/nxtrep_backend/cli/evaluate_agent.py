import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from nxtrep_backend.agents.factory import build_agent_workflow_service
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.evaluation.agent import (
    AgentEvaluationReport,
    build_agent_evaluation_report,
    evaluate_agent_response,
    failed_agent_evaluation_case,
    load_agent_asset_fixtures,
    load_agent_evaluation_cases,
    resolve_agent_evaluation_request,
)

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[1] / "evaluation" / "datasets" / "non_rag_agent.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed non-RAG Agent evaluation set against configured models.",
    )
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--asset-fixtures",
        type=Path,
        default=None,
        help="Private JSON mapping from dataset fixture keys to owned image asset UUIDs.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-below", type=float, default=1.0)
    return parser


async def run_evaluation(
    *,
    user_id: UUID,
    dataset: Path,
    asset_fixture_path: Path | None = None,
) -> AgentEvaluationReport:
    cases = load_agent_evaluation_cases(dataset)
    asset_fixtures = (
        load_agent_asset_fixtures(asset_fixture_path) if asset_fixture_path is not None else {}
    )
    results = []

    async with SessionFactory() as session:
        service = build_agent_workflow_service(session=session, user_id=user_id)
        for case in cases:
            try:
                request = resolve_agent_evaluation_request(case, asset_fixtures)
                response = await service.chat(user_id=user_id, request=request)
                await session.commit()
                results.append(evaluate_agent_response(case, response))
            except Exception as exc:
                await session.rollback()
                results.append(
                    failed_agent_evaluation_case(
                        case,
                        error_code=type(exc).__name__,
                    )
                )

    return build_agent_evaluation_report(results)


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()
    if not 0 <= arguments.fail_below <= 1:
        parser.error("--fail-below must be between 0 and 1")

    report = asyncio.run(
        run_evaluation(
            user_id=arguments.user_id,
            dataset=arguments.dataset,
            asset_fixture_path=arguments.asset_fixtures,
        )
    )
    serialized = report.model_dump_json(indent=2)
    print(serialized)
    if arguments.output is not None:
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    if report.pass_rate < arguments.fail_below:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
