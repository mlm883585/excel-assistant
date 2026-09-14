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
        from .workbooks import Workbooks
        service = Workbooks(store)
        books = service.list(task)
        for book in books:
            book['sheets'] = [{'id': s['id'], 'name': s['name']} for s in service.load(task, book['id'])['snapshot']['sheets']]
        return {"inputs": record["files"], "outputs": record["outputs"], 'workbooks': books}

    @server.tool()
    def datacraft_inspect(file_id: str) -> dict:
        """读取工作表目录；表头由用户确认，不猜测。"""
        path, info = store.resolve_file(task, file_id)
        if info.get('kind') == 'workbook_candidate':
            import json
            snapshot = json.loads(path.read_text(encoding='utf-8'))
            return {'sheets':[s['name'] for s in snapshot['sheets']],'note':'待用户整份核对的工作簿候选；模型不能采用或导出'}
        return overview(path)

    @server.tool()
    def datacraft_preview(selection: InputSelection, offset: int = 0, limit: int = 50) -> dict:
        """分页读取数据（最多 200 行），返回真实总行数与来源列。"""
        return preview(store, task, selection.model_dump(), offset, limit)

    @server.tool()
    def datacraft_execute(operation: Operation) -> dict:
        """生成候选结果，不代替用户采用或导出。join: keys/how/validate；group: keys/columns/aggregate；melt: keys/columns；pivot: keys/column/value/aggregate；clean: config(schema_version=1)；template: sheet/start_row/mapping。
        calculate params={columns:[{name:'金额',expression:{op:'multiply',args:[{field:'数量'},{field:'单价'}]}}]}，仅 add/subtract/multiply/divide/round/min/max/abs；round 第二参数为 {number:2}。
        classify params={columns:[{name:'等级',rules:[{when:{field:'金额',operator:'ge',value:100},label:'高'}],default:'普通'}]}。条件允许 all/any 数组及 eq/ne/gt/ge/lt/le。
        create_table inputs=[]，params={name,sheet_name,columns:['字段'],rows:[[null]],blank_rows:20}。只填用户明确提供的数据，缺失数字 null；用户明确要求示例才使用 example_data:true 并注明。
        edit_workbook 需要工作簿输入（workbook_id/version/sheet_id/range），params={edits:[{kind:'set_values',range:{r0:1,c0:0,r1:1,c1:0},values:[[1]]}]}。范围零基含结束。还允许 set_style(style:font_name/font_size/bold/italic/font_color/bg_color/align/valign/text_wrap/num_format/borders)、add_sheet(name)、rename_sheet(name)。不可执行任意内核命令。所有业务歧义先询问；不得扩大用户选区。"""
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
        if info.get('kind') == 'workbook_candidate':
            from .workbooks import Workbooks
            return {'readable': True, 'candidate': True, 'review': Workbooks(store).review(task, file_id)}
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
