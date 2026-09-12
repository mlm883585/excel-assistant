from __future__ import annotations

import argparse
import sys
import tempfile
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

import pandas as pd

from .audit import finish_run, new_run, write_json_atomic
from .cleaning import clean_dataframe, suggest_header_mappings
from .config import ToolConfig, load_config, parse_config
from .database import check_database, connect_database
from .database_config import load_database_config
from .database_export import export_spool, profile_spool, spool_cursor
from .engine import choose_engine
from .io import read_table, write_table
from .models import DataIssue, ToolkitError
from .profiling import profile_dataframe
from .reconcile import compare_dataframes, merge_dataframes
from .reporting import issues_frame, write_report
from .sql_runner import run_query


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-tool", description="DataCraft（数据工坊）：通用离线数据工具箱")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="分析字段、空值、唯一值和问题")
    inspect.add_argument("input")
    inspect.add_argument("--sheet")
    inspect.add_argument("--config")
    inspect.add_argument("--engine", choices=["auto", "pandas", "polars"], default="auto")
    inspect.add_argument("--report")

    clean = subparsers.add_parser("clean", help="按 JSON 配置清洗数据")
    clean.add_argument("input")
    clean.add_argument("--config", required=True)
    clean.add_argument("-o", "--output", required=True)
    clean.add_argument("--sheet")
    clean.add_argument("--engine", choices=["auto", "pandas", "polars"], default="auto")

    merge = subparsers.add_parser("merge", help="追加或连接多个数据文件")
    merge.add_argument("inputs", nargs="+")
    merge.add_argument("--config", required=True)
    merge.add_argument("-o", "--output", required=True)
    merge.add_argument("--engine", choices=["auto", "pandas", "polars"], default="auto")

    compare = subparsers.add_parser("compare", help="按单键或组合键对账")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument("--config", required=True)
    compare.add_argument("-o", "--output", required=True, help="对账报告 .xlsx")
    compare.add_argument("--engine", choices=["auto", "pandas", "polars"], default="auto")

    sql = subparsers.add_parser("sql", help="用 DuckDB 执行一条只读 SELECT/WITH 查询")
    sql.add_argument("--table", action="append", required=True, metavar="NAME=PATH")
    sql.add_argument("--query-file", required=True)
    sql.add_argument("-o", "--output", required=True)

    convert = subparsers.add_parser("convert", help="在 Excel、CSV、TSV、Parquet 之间转换")
    convert.add_argument("input")
    convert.add_argument("-o", "--output", required=True)
    convert.add_argument("--sheet")
    convert.add_argument("--config")
    convert.add_argument("--engine", choices=["auto", "pandas", "polars"], default="auto")

    db_query = subparsers.add_parser("db-query", help="执行 MySQL/SQL Server 单条只读查询")
    db_query.add_argument("--connection", required=True, help="数据库连接 JSON 配置")
    query_mode = db_query.add_mutually_exclusive_group(required=True)
    query_mode.add_argument("--check", action="store_true", help="只检查连接并执行 SELECT 1")
    query_mode.add_argument("--query-file", help="UTF-8 只读 SQL 文件")
    db_query.add_argument("-o", "--output")
    db_query.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    db_query.add_argument("--chunk-size", type=int, default=50_000)

    kingdee = subparsers.add_parser("kingdee-bom", help="从 SQL Server 严格递归展开金蝶 BOM")
    kingdee.add_argument("--connection", required=True, help="SQL Server 连接 JSON 配置")
    kingdee.add_argument("--material-number", required=True)
    kingdee.add_argument("--bom-version", required=True)
    kingdee.add_argument("--root-qty", required=True)
    kingdee.add_argument("-o", "--output", required=True)
    kingdee.add_argument("--chunk-size", type=int, default=50_000)
    return parser


def _empty_config() -> ToolConfig:
    return parse_config({"schema_version": 1, "columns": {}})


def _load(path: str | None) -> ToolConfig:
    return load_config(path) if path else _empty_config()


def _report_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}_质检报告.xlsx")


def _log_path(output_or_report: Path) -> Path:
    return output_or_report.with_name(f"{output_or_report.stem}_运行日志.json")


def _ensure_available(outputs: list[Path], inputs: list[Path]) -> None:
    input_resolved = {path.resolve() for path in inputs}
    seen: set[Path] = set()
    for output in outputs:
        resolved = output.resolve()
        if resolved in input_resolved:
            raise ToolkitError(f"禁止覆盖输入文件: {output}")
        if resolved in seen:
            raise ToolkitError(f"多个输出路径冲突: {output}")
        if output.exists():
            raise ToolkitError(f"输出文件已存在，拒绝覆盖: {output}")
        seen.add(resolved)


def _read(path: Path, config: ToolConfig, engine: str, sheet: str | None = None) -> pd.DataFrame:
    return read_table(
        path,
        sheet=sheet or config.input.sheet,
        header_row=config.input.header_row,
        engine=engine,
        encoding=config.input.encoding,
    )


def _suggestions_frame(frame: pd.DataFrame, config: ToolConfig) -> pd.DataFrame:
    suggestions = suggest_header_mappings(frame.columns.astype(str), config, threshold=90)
    return pd.DataFrame(
        [{"源字段": item.source, "建议字段": item.target, "相似度": item.score, "说明": "仅建议，未自动修改"} for item in suggestions],
        columns=["源字段", "建议字段", "相似度", "说明"],
    )


def _audit(
    log: Path,
    run: dict[str, object],
    *,
    inputs: list[Path],
    outputs: list[Path],
    rows: int,
    issues: list[DataIssue],
    started: float,
) -> None:
    payload = finish_run(run, inputs=inputs, outputs=outputs, row_count=rows, issues=issues, elapsed_seconds=time.perf_counter() - started)
    write_json_atomic(log, payload)


def _inspect(args: argparse.Namespace) -> int:
    source = Path(args.input)
    config = _load(args.config)
    engine = choose_engine("inspect", [source], args.engine)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = Path(args.report) if args.report else source.with_name(f"{source.stem}_分析报告_{timestamp}.xlsx")
    log = _log_path(report)
    _ensure_available([report, log], [source])
    started = time.perf_counter()
    run = new_run("inspect", engine)
    frame = _read(source, config, engine, args.sheet)
    result = clean_dataframe(frame, config, str(source)) if config.columns else None
    data = result.data if result else frame
    issues = result.issues if result else []
    write_report(
        report,
        summary={"命令": "inspect", "输入文件": str(source.resolve()), "引擎": engine, "记录数": len(data), "字段数": len(data.columns), "问题数": len(issues)},
        field_profile=profile_dataframe(data),
        issues=issues_frame(issues),
        extras={"字段映射建议": _suggestions_frame(frame, config)},
    )
    _audit(log, run, inputs=[source], outputs=[report], rows=len(data), issues=issues, started=started)
    print(f"分析完成: {report}")
    return 1 if issues else 0


def _clean(args: argparse.Namespace) -> int:
    source, output = Path(args.input), Path(args.output)
    config = _load(args.config)
    engine = choose_engine("clean", [source], args.engine)
    report, log = _report_path(output), _log_path(output)
    _ensure_available([output, report, log], [source])
    started = time.perf_counter()
    run = new_run("clean", engine)
    result = clean_dataframe(_read(source, config, engine, args.sheet), config, str(source))
    write_table(result.data, output, id_columns=config.input.id_columns)
    write_report(
        report,
        summary={"命令": "clean", "输入文件": str(source.resolve()), "引擎": engine, "输出记录数": len(result.data), "问题数": len(result.issues)},
        field_profile=profile_dataframe(result.data),
        issues=issues_frame(result.issues),
        extras={"字段映射建议": pd.DataFrame([item.to_dict() for item in result.suggestions])},
    )
    _audit(log, run, inputs=[source], outputs=[output, report], rows=len(result.data), issues=result.issues, started=started)
    print(f"清洗完成: {output}")
    return 1 if result.issues else 0


def _merge(args: argparse.Namespace) -> int:
    inputs = [Path(item) for item in args.inputs]
    output = Path(args.output)
    config = _load(args.config)
    engine = choose_engine("merge", inputs, args.engine)
    report, log = _report_path(output), _log_path(output)
    _ensure_available([output, report, log], inputs)
    started = time.perf_counter()
    run = new_run("merge", engine)
    frames: list[pd.DataFrame] = []
    issues: list[DataIssue] = []
    for source in inputs:
        frame = _read(source, config, engine)
        if config.columns:
            cleaned = clean_dataframe(frame, config, str(source))
            frames.append(cleaned.data)
            issues.extend(cleaned.issues)
        else:
            frames.append(frame)
    merged = merge_dataframes(frames, config)
    write_table(merged.data, output, id_columns=config.input.id_columns)
    write_report(
        report,
        summary={"命令": "merge", "输入文件数": len(inputs), "引擎": engine, "输出记录数": len(merged.data), "问题数": len(issues)},
        field_profile=profile_dataframe(merged.data),
        issues=issues_frame(issues),
        extras={"左表未匹配": merged.unmatched_left, "右表未匹配": merged.unmatched_right},
    )
    _audit(log, run, inputs=inputs, outputs=[output, report], rows=len(merged.data), issues=issues, started=started)
    print(f"合并完成: {output}")
    return 1 if issues else 0


def _compare(args: argparse.Namespace) -> int:
    left_path, right_path, report = Path(args.left), Path(args.right), Path(args.output)
    if report.suffix.lower() != ".xlsx":
        raise ToolkitError("compare 输出必须为 .xlsx 报告")
    config = _load(args.config)
    engine = choose_engine("compare", [left_path, right_path], args.engine)
    log = _log_path(report)
    _ensure_available([report, log], [left_path, right_path])
    started = time.perf_counter()
    run = new_run("compare", engine)
    left = _read(left_path, config, engine)
    right = _read(right_path, config, engine)
    issues: list[DataIssue] = []
    if config.columns:
        left_cleaned = clean_dataframe(left, config, str(left_path))
        right_cleaned = clean_dataframe(right, config, str(right_path))
        left, right = left_cleaned.data, right_cleaned.data
        issues.extend(left_cleaned.issues)
        issues.extend(right_cleaned.issues)
    result = compare_dataframes(left, right, config)
    write_report(
        report,
        summary={"命令": "compare", "引擎": engine, "左表记录数": len(left), "右表记录数": len(right), "新增数": len(result.added), "删除数": len(result.removed), "变更字段数": len(result.changed)},
        field_profile=pd.concat([profile_dataframe(left).assign(数据集="左表"), profile_dataframe(right).assign(数据集="右表")], ignore_index=True),
        issues=issues_frame(issues),
        extras={"新增": result.added, "删除": result.removed, "字段差异": result.changed},
    )
    _audit(log, run, inputs=[left_path, right_path], outputs=[report], rows=len(result.added) + len(result.removed) + len(result.changed), issues=issues, started=started)
    print(f"对账完成: {report}")
    return 1 if issues else 0


def _parse_tables(values: list[str]) -> dict[str, Path]:
    tables: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ToolkitError(f"--table 必须使用 NAME=PATH 格式: {value}")
        name, path_text = value.split("=", 1)
        if not name or not path_text or name in tables:
            raise ToolkitError(f"无效或重复的 --table: {value}")
        tables[name] = Path(path_text)
    return tables


def _sql(args: argparse.Namespace) -> int:
    paths = _parse_tables(args.table)
    query_path, output = Path(args.query_file), Path(args.output)
    report, log = _report_path(output), _log_path(output)
    _ensure_available([output, report, log], [*paths.values(), query_path])
    if not query_path.is_file():
        raise ToolkitError(f"SQL 文件不存在: {query_path}")
    started = time.perf_counter()
    run = new_run("sql", "duckdb")
    tables = {
        name: read_table(path, engine=choose_engine("inspect", [path], "auto"))
        for name, path in paths.items()
    }
    query = query_path.read_text(encoding="utf-8-sig")
    result = run_query(tables, query)
    write_table(result, output)
    write_report(
        report,
        summary={"命令": "sql", "引擎": "duckdb", "输入表数": len(tables), "输出记录数": len(result)},
        field_profile=profile_dataframe(result),
        issues=pd.DataFrame(columns=["严重级别", "问题代码", "消息"]),
    )
    _audit(log, run, inputs=[*paths.values(), query_path], outputs=[output, report], rows=len(result), issues=[], started=started)
    print(f"SQL 分析完成: {output}")
    return 0


def _convert(args: argparse.Namespace) -> int:
    source, output = Path(args.input), Path(args.output)
    config = _load(args.config)
    engine = choose_engine("convert", [source], args.engine)
    report, log = _report_path(output), _log_path(output)
    _ensure_available([output, report, log], [source])
    started = time.perf_counter()
    run = new_run("convert", engine)
    frame = _read(source, config, engine, args.sheet)
    issues: list[DataIssue] = []
    if config.columns:
        cleaned = clean_dataframe(frame, config, str(source))
        frame, issues = cleaned.data, cleaned.issues
    write_table(frame, output, id_columns=config.input.id_columns)
    write_report(
        report,
        summary={"命令": "convert", "输入文件": str(source.resolve()), "引擎": engine, "输出记录数": len(frame), "问题数": len(issues)},
        field_profile=profile_dataframe(frame),
        issues=issues_frame(issues),
    )
    _audit(log, run, inputs=[source], outputs=[output, report], rows=len(frame), issues=issues, started=started)
    print(f"转换完成: {output}")
    return 1 if issues else 0


def _parse_query_parameters(values: list[str]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ToolkitError(f"--param 必须使用 NAME=VALUE 格式: {value}")
        name, parameter_value = value.split("=", 1)
        if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
            raise ToolkitError(f"无效 SQL 参数名: {name}")
        if name in parameters:
            raise ToolkitError(f"重复 SQL 参数: {name}")
        parameters[name] = parameter_value
    return parameters


def _database_metadata(config: object, driver: str | None) -> dict[str, object]:
    return {
        "type": getattr(config, "type"),
        "host": getattr(config, "host"),
        "port": getattr(config, "port"),
        "database": getattr(config, "database"),
        "driver": driver,
    }


def _write_database_outputs(
    *,
    command: str,
    config_path: Path,
    query_path: Path,
    output: Path,
    parameters: dict[str, object],
    chunk_size: int,
    trusted: bool,
    summary_extra: dict[str, object] | None = None,
    session: object | None = None,
) -> int:
    report, log = _report_path(output), _log_path(output)
    _ensure_available([output, report, log], [config_path, query_path])
    if not query_path.is_file():
        raise ToolkitError(f"SQL 文件不存在: {query_path}")
    if not 1_000 <= chunk_size <= 500_000:
        raise ToolkitError("chunk-size 必须在 1000–500000 之间")
    config = load_database_config(config_path)
    query = query_path.read_text(encoding="utf-8-sig")
    started = time.perf_counter()
    run = new_run(command, config.type)
    run["parameter_names"] = sorted(parameters)
    run["chunk_size"] = chunk_size

    with tempfile.TemporaryDirectory(prefix="kingdee-data-tool-") as temp_dir:
        owns_session = session is None
        active_session = connect_database(config) if session is None else session
        try:
            cursor = active_session.execute(query, parameters, trusted=trusted)
            try:
                spool = spool_cursor(cursor, Path(temp_dir), chunk_size=chunk_size)
            finally:
                cursor.close()
            run["database"] = _database_metadata(config, getattr(active_session, "driver", None))
            run["chunk_count"] = spool.chunk_count
            export_spool(spool, output)
            profile = profile_spool(spool)
        finally:
            if owns_session:
                active_session.close()

        summary = {
            "命令": command,
            "数据库类型": config.type,
            "服务器": f"{config.host}:{config.port}",
            "数据库": config.database,
            "输出记录数": spool.row_count,
            "分块数": spool.chunk_count,
        }
        summary.update(summary_extra or {})
        write_report(
            report,
            summary=summary,
            field_profile=profile,
            issues=pd.DataFrame(columns=["严重级别", "问题代码", "消息"]),
        )
        _audit(
            log,
            run,
            inputs=[config_path, query_path],
            outputs=[output, report],
            rows=spool.row_count,
            issues=[],
            started=started,
        )
    print(f"数据库查询完成: {output}")
    return 0


def _db_query(args: argparse.Namespace) -> int:
    config_path = Path(args.connection)
    config = load_database_config(config_path)
    if args.check:
        result = check_database(config)
        driver = f"，驱动 {result['driver']}" if result.get("driver") else ""
        print(
            f"连接成功: {result['type']} {result['host']}:{result['port']}/"
            f"{result['database']}{driver}"
        )
        return 0
    if not args.output:
        raise ToolkitError("db-query 使用 --query-file 时必须同时指定 -o/--output")
    return _write_database_outputs(
        command="db-query",
        config_path=config_path,
        query_path=Path(args.query_file),
        output=Path(args.output),
        parameters=_parse_query_parameters(args.param),
        chunk_size=args.chunk_size,
        trusted=False,
    )


def _kingdee_bom(args: argparse.Namespace) -> int:
    config_path = Path(args.connection)
    config = load_database_config(config_path)
    if config.type != "sqlserver":
        raise ToolkitError("kingdee-bom 仅支持 SQL Server 连接配置")
    try:
        root_quantity = Decimal(args.root_qty)
    except InvalidOperation as exc:
        raise ToolkitError(f"根数量不是有效数字: {args.root_qty}") from exc
    if not root_quantity.is_finite() or root_quantity <= 0:
        raise ToolkitError("根数量必须是大于零的有限数字")
    sql_folder = Path(__file__).with_name("sql")
    root_check_path = sql_folder / "kingdee_bom_root_check.sql"
    query_path = sql_folder / "kingdee_bom.sql"
    parameters: dict[str, object] = {
        "MaterialNumber": args.material_number,
        "BomVersion": args.bom_version,
        "RootQty": root_quantity,
    }
    with connect_database(config) as session:
        root_cursor = session.execute(
            root_check_path.read_text(encoding="utf-8-sig"),
            {"MaterialNumber": args.material_number, "BomVersion": args.bom_version},
            trusted=True,
        )
        try:
            root_row = root_cursor.fetchone()
        finally:
            root_cursor.close()
        root_count = int(root_row[0]) if root_row else 0
        if root_count == 0:
            raise ToolkitError(
                f"找不到已审核且未禁用的根 BOM: {args.material_number} / {args.bom_version}"
            )
        if root_count > 1:
            raise ToolkitError(
                f"根 BOM 匹配到 {root_count} 条记录，无法确定唯一 BOM: "
                f"{args.material_number} / {args.bom_version}"
            )
        return _write_database_outputs(
            command="kingdee-bom",
            config_path=config_path,
            query_path=query_path,
            output=Path(args.output),
            parameters=parameters,
            chunk_size=args.chunk_size,
            trusted=True,
            summary_extra={
                "根物料编码": args.material_number,
                "BOM版本": args.bom_version,
                "根数量": str(root_quantity),
            },
            session=session,
        )


COMMANDS = {
    "inspect": _inspect,
    "clean": _clean,
    "merge": _merge,
    "compare": _compare,
    "sql": _sql,
    "convert": _convert,
    "db-query": _db_query,
    "kingdee-bom": _kingdee_bom,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        return COMMANDS[args.command](args)
    except ToolkitError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"未预期的处理错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
