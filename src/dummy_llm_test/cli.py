from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import click

from .catalog import catalog
from .config import load_config, secret_values
from .core import DATA, PACKAGE, read_json, scrub, write_json
from .fingerprint import analyze, challenges, load_bank, load_challenges
from .report import compare as compare_runs
from .report import export_review, import_review, regrade
from .runner import plan_run, preflight
from .runner import run as execute_run
from .scheduler import RunInterrupted


class SafeGroup(click.Group):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except (ValueError, OSError, KeyError) as exc:
            config = ctx.obj or {"targets": {}}
            raise click.ClickException(scrub(str(exc), secret_values(config))) from exc


@click.group(cls=SafeGroup)
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True), help="YAML 配置路径")
@click.version_option(package_name="dummy-llm-test")
@click.pass_context
def main(ctx, config_path):
    """社区验智、模型指纹与能力回归；开放题人工评阅。"""
    ctx.obj = load_config(config_path)


@main.command("list")
@click.option("--level", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def list_cases(config, level, as_json):
    """列出题库，或查看某个档位的全部题目。"""
    cases = (
        plan_run(config, level, [config["default_target"]], config["mode"])[1] if level else catalog(config)
    )
    if as_json:
        click.echo(
            json.dumps(
                [{"id": c.id, "suite": c.suite, "kind": c.kind, "hash": c.hash} for c in cases],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(f"{len(cases)} 题 · {dict(Counter(c.suite for c in cases))}")
        for c in cases:
            click.echo(f"{c.id:42} {c.kind}")


@main.command()
@click.option("--target", multiple=True)
@click.option("--mode", type=click.Choice(["controlled", "native"]), default=None)
@click.pass_obj
def doctor(config, target, mode):
    """只读检查依赖、题库完整性和入口配置；不会调用模型。"""
    errors = []
    for entry in read_json(DATA / "sources.json"):
        local = entry.get("local") or entry.get("extracted_local")
        checksum = entry.get("sha256") if entry.get("local") else entry.get("extracted_sha256")
        if local and hashlib.sha256((PACKAGE / local).read_bytes()).hexdigest() != checksum:
            errors.append(f"来源校验失败: {local}")
    load_bank(config.get("bank"))
    targets = list(target) or [config["default_target"]]
    for name in targets:
        try:
            identity = preflight(config, [name], mode or config["mode"])[name]
            click.echo(
                json.dumps(
                    {
                        "target": name,
                        "status": "ready_not_live_verified",
                        "identity": scrub(identity, secret_values(config)),
                    },
                    ensure_ascii=False,
                )
            )
        except (ValueError, KeyError, OSError) as exc:
            errors.append(f"{name}: {exc}")
    click.echo(f"题库 {len(catalog(config))} 题；ModelTrace 指纹库已解析；来源文件已核验。")
    if errors:
        raise click.ClickException(scrub("\n".join(errors), secret_values(config)))


@main.command("run")
@click.option("--level", default=None, help="quick / full / fingerprint / 自定义 level")
@click.option("--target", multiple=True, help="可多次传入")
@click.option("--mode", type=click.Choice(["controlled", "native"]), default=None)
@click.option("--repetitions", type=click.IntRange(1), default=None)
@click.option("--concurrency", type=click.IntRange(1), default=None, help="覆盖全局并发上限")
@click.option("--dry-run", is_flag=True, help="只列出计划，不调用模型")
@click.option("--resume", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.pass_obj
def run_command(config, level, target, mode, repetitions, concurrency, dry_run, resume):
    """执行评测，生成 JSONL 明细和 HTML 报告。"""
    old = read_json(resume / "manifest.json")["plan"] if resume else {}
    level = level or old.get("level", "quick")
    targets = list(target) or old.get("targets", [config["default_target"]])
    mode = mode or old.get("mode", config["mode"])
    if repetitions is not None:
        config["levels"][level]["repetitions"] = repetitions
    if concurrency is not None:
        config["concurrency"] = concurrency
    plan, _ = plan_run(config, level, targets, mode)
    click.echo(json.dumps(plan, ensure_ascii=False, indent=2))
    if dry_run:
        return
    try:
        _, summary, stopped = execute_run(config, level, targets, mode, resume, click.echo)
    except RunInterrupted:
        raise click.exceptions.Exit(130) from None
    errors = sum(
        count for group in summary["groups"] for status, count in group["statuses"].items() if status != "ok"
    )
    incomplete_fp = any(fp["status"] != "complete" for fp in summary["fingerprints"])
    if stopped or errors or incomplete_fp:
        raise click.exceptions.Exit(2)


@main.command("compare")
@click.option("--baseline", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--current", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--output", type=click.Path(path_type=Path), default=Path("runs/comparison.json"))
def compare_command(baseline, current, output):
    """匹配相同配置的逐题历史结果。"""
    result = compare_runs(baseline, current, output)
    click.echo(
        f"{dict(Counter(p['status'] for p in result['pairs']))}\n报告: {output.with_suffix('.html').resolve()}"
    )


@main.command("regrade")
@click.argument("run_dir", type=click.Path(path_type=Path, exists=True))
@click.option("--output", required=True, type=click.Path(path_type=Path))
def regrade_command(run_dir, output):
    """离线重放响应并重新判分，输出新目录，保留原始评分。"""
    summary = regrade(run_dir, output)
    click.echo(f"离线重判 {summary['completed']} 条；报告: {(output / 'report.html').resolve()}")


@main.group()
def review():
    """人工评阅包导出/导入。"""


@review.command("export")
@click.argument("run_dir", type=click.Path(path_type=Path, exists=True))
@click.option("--output", required=True, type=click.Path(path_type=Path))
def review_export(run_dir, output):
    count = export_review(run_dir, output)
    click.echo(f"导出 {count} 份待评样本: {(output / 'index.html').resolve()}")


@review.command("import")
@click.argument("run_dir", type=click.Path(path_type=Path, exists=True))
@click.argument("scores", type=click.Path(path_type=Path, exists=True))
def review_import(run_dir, scores):
    count = import_review(run_dir, scores)
    click.echo(f"已导入 {count} 份评分，报告已更新。")


@main.group()
def fingerprint():
    """ModelTrace 三条挑战导出与已有回答离线分析。"""


@main.group("performance")
def performance_command():
    """离线性能派生分析；不修改原始记录，不调用模型。"""


@performance_command.command("analyze")
@click.argument("run_dir", type=click.Path(path_type=Path, exists=True))
@click.option("--output", required=True, type=click.Path(path_type=Path))
def performance_analyze(run_dir, output):
    from .performance import derive

    result = derive(run_dir, output)
    click.echo(f"离线分析 {len(result['observations'])} 个样本；报告: {(output / 'report.html').resolve()}")


@fingerprint.command("export")
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option("--seed", type=int, default=None)
@click.pass_obj
def fingerprint_export(config, output, seed):
    seed = config["seed"] if seed is None else seed
    probes = challenges(seed)
    write_json(output, {"schema_version": 1, "seed": seed, "challenges": probes})
    write_json(
        output.with_name(output.stem + "-answers.json"),
        {"outputs": [{"id": p["id"], "text": "", "status": "ok", "tools": []} for p in probes]},
    )
    click.echo(f"三条挑战: {output.resolve()}；相邻 answers.json 填写完整回答。")


@fingerprint.command("analyze")
@click.option("--challenges", "challenge_path", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--answers", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--bank", type=click.Path(path_type=Path, exists=True), default=None)
@click.option("--output", type=click.Path(path_type=Path), default=Path("runs/fingerprint-analysis.json"))
@click.pass_obj
def fingerprint_analyze(config, challenge_path, answers, bank, output):
    probes = load_challenges(challenge_path)
    data = read_json(answers)
    rows = data["outputs"] if isinstance(data, dict) else data
    by_id = {o["id"]: o for o in rows}
    if len(by_id) != len(rows) or set(by_id) - {p["id"] for p in probes}:
        raise ValueError("回答 ID 重复或不在挑战清单中")
    outputs = [
        {**by_id.get(p["id"], {"text": "", "status": "not_run"}), "expected_count": p["expected_count"]}
        for p in probes
    ]
    result = analyze(outputs, load_bank(bank or config.get("bank")))
    result["provenance"] = "手动导入；是否调用工具由导入者声明，未由 CLI 事件核验"
    write_json(output, result)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
