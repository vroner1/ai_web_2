import asyncio

import httpx

headers = {"Content-Type": "application/json", "Authorization": "Bearer secret-key"}


async def get_response():
    async with httpx.AsyncClient(headers=headers) as cl:
        response = await cl.post(
            "http://localhost:8001/chat",
            json={"messages": [{"role": "user", "message": "test" * 2000}]},
        )
        return response


res = await get_response()

tasks = [get_response()] * 5

await asyncio.gather(*tasks)
