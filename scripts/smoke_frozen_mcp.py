"""Exercise the packaged MCP executable with the official MCP client."""
import asyncio
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from assistant.store import Store
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    exe=ROOT/'build/ExcelAssistant/mcp/DataCraftMCP.exe'
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);store=Store(root/'data');task=store.create()['id']
        source=root/'input.csv';source.write_text('code,qty\n0001,2\nNA,3\n')
        file=store.import_file(task,source)
        params=StdioServerParameters(command=str(exe),args=['--root',str(store.root),'--task',task])
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                result=await session.call_tool('datacraft_execute',{'operation':{'kind':'append','inputs':[{'file_id':file['id']}]}})
                if result.isError:raise RuntimeError(str(result))
        assert len(store.get(task)['outputs'])==1
        print('FROZEN_MCP_EXPORT_OK')


if __name__=='__main__':asyncio.run(main())
