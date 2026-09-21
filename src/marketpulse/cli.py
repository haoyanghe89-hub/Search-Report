from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from pydantic import ValidationError

from marketpulse.adapters.fetch import PageFetcher
from marketpulse.adapters.robots import RobotsPolicy
from marketpulse.adapters.search import PublicSearchClient
from marketpulse.agents.factory import DeepSeekAgentRunner
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.errors import ErrorCode, InvalidInputError, MarketPulseError
from marketpulse.observability import RunLogger, RunStats, Stage
from marketpulse.services.planner import validate_topic
from marketpulse.workflow import (
    MarketPulseRequest,
    WorkflowDependencies,
    run_marketpulse,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="联网研究市场、竞品和定价，并生成中文 Markdown 可行性报告。",
)

_STAGE_LABELS = {
    Stage.PLAN: "规划搜索",
    Stage.SEARCH: "搜索市场/竞品/定价",
    Stage.FETCH: "读取公开页面",
    Stage.EXTRACT: "整理证据",
    Stage.ANALYZE: "DeepSeek 分析",
    Stage.REVIEW: "主 Agent 复核与补查决策",
    Stage.REPORT: "报告 Agent 撰写",
    Stage.QUALITY: "质量检查",
    Stage.WRITE: "写入报告",
}


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-").lower()
    return value[:50] or "market"


def _default_output(topic: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("reports") / f"{_slug(topic)}-{stamp}.md"


async def _execute(
    topic: str,
    output: Path,
    competitors: int,
    log_file: Path | None,
    settings: Settings,
) -> None:
    stats = RunStats()
    logger = RunLogger(stats.run_id, log_file)
    budget = RunBudget.start(settings)
    runner = DeepSeekAgentRunner(settings)
    try:
        async with httpx.AsyncClient(max_redirects=5) as http_client:
            robots = RobotsPolicy(http_client, settings)
            search = PublicSearchClient(http_client, settings, budget)
            fetcher = PageFetcher(http_client, settings, budget, robots)
            deps = WorkflowDependencies(
                search=search,
                fetcher=fetcher,
                runner=runner,
                budget=budget,
                logger=logger,
                progress=lambda stage: typer.echo(f"[{stage.value}] {_STAGE_LABELS[stage]}…"),
            )
            request = MarketPulseRequest(
                topic=topic,
                competitor_limit=competitors,
                output_path=output,
            )
            result = await run_marketpulse(request, deps, settings)
            typer.echo(f"完成：{result.report_path}")
            typer.echo(
                f"run_id={result.run_id}，来源={result.stats.sources}，"
                f"页面失败={result.stats.pages_failed}"
            )
            if result.quality.issues:
                typer.echo("覆盖提示：" + "；".join(item.message for item in result.quality.issues))
    finally:
        await runner.aclose()


@app.callback(invoke_without_command=True)
def research(
    topic: Annotated[str, typer.Argument(help="产品方向或关键词，例如 AI meeting notes tools")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Markdown 输出路径")] = None,
    competitors: Annotated[
        int, typer.Option("--competitors", "-c", min=3, max=8, help="竞品候选上限")
    ] = 5,
    log_file: Annotated[Path | None, typer.Option("--log-file", help="JSONL 调试日志路径")] = None,
) -> None:
    """执行一次市场研究并生成报告。"""
    try:
        cleaned = validate_topic(topic)
        settings = Settings.from_env()
        logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
        asyncio.run(
            _execute(
                cleaned,
                output or _default_output(cleaned),
                competitors,
                log_file,
                settings,
            )
        )
    except ValidationError as exc:
        typer.echo(f"输入错误：{exc.errors()[0]['msg']}", err=True)
        raise typer.Exit(code=int(ErrorCode.INVALID_INPUT)) from exc
    except InvalidInputError as exc:
        typer.echo(f"输入错误：{exc}", err=True)
        raise typer.Exit(code=int(exc.code)) from exc
    except MarketPulseError as exc:
        typer.echo(f"执行失败：{exc}", err=True)
        raise typer.Exit(code=int(exc.code)) from exc
    except KeyboardInterrupt as exc:
        typer.echo("已取消。", err=True)
        raise typer.Exit(code=130) from exc
    except Exception as exc:
        typer.echo(f"执行失败：未预期错误（{type(exc).__name__}）。", err=True)
        raise typer.Exit(code=int(ErrorCode.INTERNAL_ERROR)) from exc


if __name__ == "__main__":
    app()
