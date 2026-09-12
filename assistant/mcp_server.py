"""Task-scoped MCP server; stdout is reserved for the MCP transport."""
import argparse
import sys
import anyio
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server
from .store import Store
from .models import InputSelection, Operation
from .tables import overview, preview, run_operation


class TaskMCP(FastMCP):
    async def run_stdio_async(self):
        # Keep the process-owned TextIOWrappers alive. Re-wrapping their buffers
        # lets GC close stdout before the frozen bootloader performs its flush.
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8")
        async with stdio_server(anyio.wrap_file(sys.stdin), anyio.wrap_file(sys.stdout)) as (reader, writer):
            await self._mcp_server.run(reader, writer, self._mcp_server.create_initialization_options())


def create_server(root: Path, task: str):
    store = Store(root)
    store.get(task)
    server = TaskMCP("datacraft_mcp")

    @server.tool()
    def datacraft_files() -> dict:
        """列出本任务导入文件及已生成文件的标识。仅能使用这些标识。"""
        record = store.get(task)
        return {"inputs": record["files"], "outputs": record["outputs"]}

    @server.tool()
    def datacraft_inspect(file_id: str) -> dict:
        """读取工作表目录；表头由用户确认，不猜测。"""
        path, _ = store.resolve_file(task, file_id)
        return overview(path)

    @server.tool()
    def datacraft_preview(selection: InputSelection, offset: int = 0, limit: int = 50) -> dict:
        """分页读取数据（最多 200 行），返回真实总行数与来源列。"""
        return preview(store, task, selection.model_dump(), offset, limit)

    @server.tool()
    def datacraft_execute(operation: Operation) -> dict:
        """执行确定性操作并校验导出。join params: keys/how/validate；group: keys/columns/aggregate；melt: keys/columns；pivot: keys/column/value/aggregate；clean: config(DataCraft schema_version=1)；template: sheet/start_row/mapping。业务歧义先询问用户。"""
        result = run_operation(store, task, operation.model_dump())
        record = store.get(task)
        plan = record.get("plan") or {"steps": [], "questions": []}
        plan["steps"].append(operation.model_dump())
        record["plan"] = plan
        store.save(record)
        store.event(task, "output", result)
        return result

    @server.tool()
    def datacraft_validate(file_id: str) -> dict:
        """验证本任务生成的 xlsx 可重新读取；不代替业务数值核对或 Excel 实机验收。"""
        from openpyxl import load_workbook
        path, info = store.resolve_file(task, file_id)
        if not info.get("validated"):
            raise ValueError("此文件不是已登记的输出")
        book = load_workbook(path, read_only=True)
        try:
            return {"readable": True, "sheets": book.sheetnames, "statistics": info.get("statistics", {})}
        finally:
            book.close()

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    create_server(Path(args.root), args.task).run(transport="stdio")


if __name__ == "__main__":
    main()
