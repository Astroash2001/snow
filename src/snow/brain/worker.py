"""Brain worker: answers each transcript.final via the first usable `fast` provider.

Provider, base URL and model come only from config/models.toml (CORE-04). The key is
read from Credential Manager at call time and never stored (SAFE-09). Plan 01-08 adds
the fallback chain and durable error events.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI, OpenAIError

from snow.brain.config import ChainEntry, ModelsConfig, PersonaConfig, Provider
from snow.config.secrets import Secret, get_secret
from snow.config.settings import load_config
from snow.contracts.events import Event, ReplyDelta, ReplyFinal, TranscriptFinal

log = logging.getLogger("snow.brain")

Publish = Callable[[Event], Awaitable[None]]


def _pick(models: ModelsConfig) -> tuple[ChainEntry, Provider, Secret] | None:
    role = models.roles.get("fast")
    for entry in role.chain if role else []:
        provider = models.providers[entry.provider]
        secret = get_secret(provider.key_name)
        if secret is not None:
            return entry, provider, secret
    return None


class BrainWorker:
    def __init__(self, publish: Publish) -> None:
        self._publish = publish

    async def on_event(self, event: Event) -> None:
        if isinstance(event, TranscriptFinal):
            await self._answer(event)

    async def _answer(self, heard: TranscriptFinal) -> None:
        # Config is re-read every turn so a models.toml edit applies with no restart.
        try:
            models = load_config("models.toml", ModelsConfig)
            persona = load_config("persona.toml", PersonaConfig)
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        picked = _pick(models)
        if picked is None:
            log.error("no_provider_key")
            return
        entry, provider, secret = picked
        cid, tid, cause = heard.correlation_id, heard.turn_id, heard.seq
        text = ""
        try:
            async with AsyncOpenAI(
                base_url=provider.base_url,
                api_key=secret.reveal(),
                max_retries=0,  # SDK retries would delay failover (research F6)
                timeout=30,
            ) as client:
                stream = await client.chat.completions.create(
                    model=entry.model,
                    messages=[
                        {"role": "system", "content": persona.system_prompt},
                        {"role": "user", "content": heard.text},
                    ],
                    stream=True,
                    extra_body={
                        k: v
                        for k, v in entry.params.items()
                        if k not in entry.drop_params
                    },
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        text += delta
                        await self._publish(
                            ReplyDelta(
                                ts_ns=time.time_ns(),
                                source="brain",
                                correlation_id=cid,
                                turn_id=tid,
                                causation_id=cause,
                                text=delta,
                            )
                        )
        except OpenAIError as e:
            log.error("llm_error kind=%s provider=%s", type(e).__name__, entry.provider)
            if not text:
                # Failed before the first token: no reply.final (plan 01-08 records it).
                return
        await self._publish(
            ReplyFinal(
                ts_ns=time.time_ns(),
                source="brain",
                text=text,
                emotion="neutral",
                big_moment=False,
                reply_source="llm",
                provider=entry.provider,
                model=entry.model,
                correlation_id=cid,
                turn_id=tid,
                causation_id=cause,
            )
        )
