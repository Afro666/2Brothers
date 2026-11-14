"""Run the buyer with live Nemotron and either the real or explicit mock gateway."""
import argparse
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from agent.model import Nemotron
from agent.runner import Buyer
from agent.usage import emit
from gateway.mcp_server import GatewayClient, build_server
from gateway.mock_gateway import MockGateway


async def run(args):
    load_dotenv(Path.cwd() / ".env", override=False)
    model = Nemotron()
    gateway = GatewayClient(transport=httpx.MockTransport(MockGateway()) if args.mock else None)
    run_id = str(uuid4())
    options = {"need_id": args.need_id, "requested_date": args.date,
               "max_steps": args.max_steps, "run_id": run_id,
               "trace_path": Path(".local/traces") / f"{run_id}.jsonl"}
    try:
        if args.mock:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                result = await Buyer(model, session, gateway, **options).run(args.request)
        else:
            # Never pass inference or upstream secrets to the MCP subprocess.
            env = {"GATEWAY_BASE_URL": os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:8000")}
            params = StdioServerParameters(command=sys.executable, args=["-m", "gateway.mcp_server"], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await Buyer(model, session, gateway, **options).run(args.request)
        result["mode"] = "mock_gateway_live_nemotron" if args.mock else "live_gateway_live_nemotron"
        result["usage"] = model.meter.total()
        return result
    finally:
        emit(model.meter, run="buyer")
        await gateway.close()
        await model.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    parser.add_argument("--need-id", required=True, help="Stored need created by trusted application/engine")
    parser.add_argument("--date", required=True, type=lambda v: date.fromisoformat(v).isoformat())
    parser.add_argument("--max-steps", default=12, type=int)
    parser.add_argument("--mock", action="store_true", help="Mock gateway, live Nemotron; uses inference credits")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception:
        print(json.dumps({"status": "CANNOT_FULFIL", "reason": "Agent setup or transport failed; check local configuration"}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "CANNOT_FULFIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
