import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("=== Tools the server exposes ===")
            tools = await session.list_tools()
            for t in tools.tools:
                print("-", t.name, ":", (t.description or "").split("\n")[0])

            print("\n=== top_customers(2) ===")
            r = await session.call_tool("top_customers", {"n": 2})
            print(r.content[0].text)

            print("\n=== Guardrail test ($out) ===")
            r = await session.call_tool(
                "run_aggregation",
                {"collection": "orders", "pipeline": [{"$out": "hacked"}]},
            )
            print(r.content[0].text)


asyncio.run(main())
