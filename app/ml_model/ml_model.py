import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class MockLLM:
    def __init__(self) -> None:
        logger.info("[Weights are loading].")
        time.sleep(3)
        logger.info("[Weights are loaded].")
        self.semaphore = asyncio.Semaphore(2)

    async def generate(self, prompt: str, temperature: float, max_tokens: int):

        async with self.semaphore:
            logger.info(
                f"Generating response on `prompt`: {prompt[:10]}... with `temperature`:{temperature}"
            )
            logger.info(f"Slots available: {2 - self.semaphore._value}/2.")
            await asyncio.sleep(2)
            return f"Response with `temperature`:{temperature} for `prompt`: {prompt[:10]}..."

    async def generate_stream(self, prompt: str, temperature: float, max_tokens: int):
        await asyncio.sleep(1)

        words = prompt.split(" ")

        for word in words:
            await asyncio.sleep(0.3)
            yield f"{word} "
