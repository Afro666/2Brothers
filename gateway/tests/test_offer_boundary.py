import asyncio
import httpx
from mcp.shared.memory import create_connected_server_and_client_session
from gateway.mcp_server import GatewayClient, build_server
from agent.runner import unpack


def test_mcp_offer_requires_separate_simulation():
    async def run():
        def response(request):
            return httpx.Response(200, json={'offer_id': 'o', 'valid_until': '2099-01-01T00:00:00Z',
                'lines': [], 'expected_total': '1.00', 'mandate': {'verdict': 'NEEDS_APPROVAL'}})
        client = GatewayClient(transport=httpx.MockTransport(response))
        try:
            async with create_connected_server_and_client_session(build_server(client)) as session:
                offer = await session.call_tool('get_offer', {'product_ids': ['p'],
                    'requested_date': '2026-11-16', 'need_id': 'n'})
                assert set(unpack(offer)) == {'offer_id', 'valid_until', 'lines'}
                simulation = await session.call_tool('simulate_order', {'offer_id': 'o'})
                assert unpack(simulation)['expected_total'] == '1.00'
        finally:
            await client.close()
    asyncio.run(run())
