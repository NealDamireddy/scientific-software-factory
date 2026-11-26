"""Read the shared reference library through a local stdio MCP client."""
import argparse
import asyncio
import json
import sys
from urllib.parse import quote

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    uri = "labfactory://references/catalog"
    if args.objective:
        uri = f"labfactory://references/search/{quote(args.instrument, safe='')}/{quote(args.objective, safe='')}"
    server = StdioServerParameters(command=sys.executable, args=["-m", "labfactory", "--db", ":memory:", "serve"])
    async with stdio_client(server) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        data = json.loads((await session.read_resource(uri)).contents[0].text)
    if not args.objective:
        for item in data["instruments"]:
            print(item["id"], "·", item["manufacturer"], item["model"])
        return
    print(data["overview"])
    if data.get("requirements"):
        print(data["requirements"])
    for item in data["findings"]:
        print(f"\n{item['kind'].upper()} · {item['title']}\n{item['reason']}\n{item['summary']}"
              f"\nApplicability: {item['scope']}\n{item['locator']}\n{item['url']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("objective", nargs="?", help="An experiment objective. Omit to list instrument IDs.")
    parser.add_argument("--instrument", default="all", help="A model ID, technique scope ID, or all")
    asyncio.run(run(parser.parse_args()))
