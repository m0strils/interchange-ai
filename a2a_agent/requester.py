"""The `requester` agent — the *other* side of the A2A handoff (ADR-0013).

What a peer agent actually has to do, in order, and why each step is here:

1. **Fetch and verify the Agent Card** before sending anything. An unverified
   card is just a claim; acting on one means talking to whoever answered. The
   verifier pins ``algorithms=["ES256"]`` and our own key set (``a2a_agent.keys``)
   and refuses any ``jku``, so a card cannot nominate the key that checks it.
   A tampered, unsigned, or unknown-``kid`` card raises here and nothing is sent.
2. **Send the question as a task, not a call**, and consume the event stream —
   status updates as the work progresses, then the answer as an artifact. This
   is the part a plain REST call has no vocabulary for.
3. **Show the governance trail**: the answer, whether it passed the grounding
   check, and the audit row the knowledge agent wrote — caller, engine, model,
   shadow cost. The point of the demo is that the handoff is *accounted for*.

Run it against a local server (see ``make a2a-demo``, which starts one)::

    python -m a2a_agent.requester --url http://127.0.0.1:8765 \
        --profile rail --api-key demo-key
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, TaskState

from a2a_agent import keys, server
from a2a_agent.profiles import load_profile

#: Exit code for "the agent refused or failed the task" — distinct from a crash.
TASK_FAILED_EXIT = 2


# --- reading the card ------------------------------------------------------
def card_kid(card: AgentCard) -> str | None:
    """The key id the card was signed with, from its first signature header."""
    for signature in card.signatures:
        protected = signature.protected
        padding = "=" * (-len(protected) % 4)
        try:
            header = json.loads(base64.urlsafe_b64decode(protected + padding))
        except (ValueError, json.JSONDecodeError):
            continue
        if header.get("kid"):
            return header["kid"]
    return None


def card_interfaces(card: AgentCard) -> str:
    """The protocol versions the card advertises, e.g. ``1.0,0.3``."""
    return ",".join(i.protocol_version for i in card.supported_interfaces)


async def resolve_card(base_url: str, httpx_client: httpx.AsyncClient, verifier) -> AgentCard:
    """Fetch the Agent Card and verify its signature before trusting a word of it."""
    resolver = A2ACardResolver(httpx_client, base_url)
    return await resolver.get_agent_card(signature_verifier=verifier)


# --- sending the task ------------------------------------------------------
def _state_name(state) -> str:
    """``TASK_STATE_WORKING`` -> ``WORKING``."""
    return TaskState.Name(state).removeprefix("TASK_STATE_")


async def ask(
    question: str,
    *,
    base_url: str,
    api_key: str,
    httpx_client: httpx.AsyncClient | None = None,
    verifier=None,
    echo: bool = True,
) -> dict:
    """Verify the card, hand the question over as a task, stream the result.

    Returns ``{card, kid, interfaces, states, text, metadata, failed, reason}``.
    Prints the card verification line and each task state as it arrives when
    ``echo`` is on, so the demo output *is* the lifecycle rather than a summary
    of it.
    """
    verifier = verifier or keys.make_verifier()
    owns_client = httpx_client is None
    client_headers = {server.api_key_header(): api_key}
    if owns_client:
        httpx_client = httpx.AsyncClient(headers=client_headers, timeout=120.0)
    else:
        httpx_client.headers.update(client_headers)

    result: dict = {
        "card": None, "kid": None, "interfaces": "", "states": [],
        "text": "", "metadata": {}, "failed": False, "reason": "",
    }
    try:
        card = await resolve_card(base_url, httpx_client, verifier)
        result["card"] = card
        result["kid"] = card_kid(card)
        result["interfaces"] = card_interfaces(card)
        if echo:
            print(f"card verified kid={result['kid']} interfaces={result['interfaces']}")

        client = await create_client(
            card, ClientConfig(httpx_client=httpx_client, streaming=True)
        )
        request = SendMessageRequest(
            message=Message(
                message_id=uuid.uuid4().hex,
                role=Role.ROLE_USER,
                parts=[Part(text=question)],
            )
        )
        async for event in client.send_message(request):
            if event.HasField("status_update"):
                state = _state_name(event.status_update.status.state)
                result["states"].append(state)
                if echo:
                    print(f"status: {state}")
                if event.status_update.status.state == TaskState.TASK_STATE_FAILED:
                    result["failed"] = True
                    result["reason"] = _message_text(event.status_update.status.message)
            elif event.HasField("artifact_update"):
                artifact = event.artifact_update.artifact
                result["text"] += "".join(p.text for p in artifact.parts if p.text)
                if artifact.metadata:
                    result["metadata"] = _struct_to_dict(artifact.metadata)
            elif event.HasField("task"):
                task = event.task
                if task.status.state:
                    state = _state_name(task.status.state)
                    result["states"].append(state)
                    if echo:
                        print(f"status: {state}")
            elif event.HasField("message"):
                result["text"] += _message_text(event.message)
    finally:
        if owns_client:
            await httpx_client.aclose()
    return result


def _message_text(message) -> str:
    return "".join(p.text for p in message.parts if p.text) if message else ""


def _struct_to_dict(struct) -> dict:
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(struct)


# --- the governance trail --------------------------------------------------
def last_audit_line() -> str | None:
    """Format the knowledge agent's most recent audit row for the console.

    Read off the JSONL tail rather than returned over the wire on purpose: the
    audit log is the *server's* record, and the demo's claim is that the handoff
    landed in it — not that the client says it did.
    """
    import enterprise

    path = enterprise.AUDIT_PATH
    if not path.exists():
        return None
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        return None
    row = json.loads(rows[-1])
    return (
        f"audit: caller={row.get('caller')} engine={row.get('engine')} "
        f"model={row.get('model')} cost_usd={row.get('cost_usd')} "
        f"marginal_usd={row.get('marginal_usd')} blocked={row.get('blocked')}"
    )


# --- CLI -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="A2A requester agent: verify the Agent Card, hand over a task, "
                    "stream the result, show the audit row."
    )
    ap.add_argument("--url", default=os.environ.get("A2A_PUBLIC_URL", "http://127.0.0.1:8765"),
                    help="base URL of the knowledge agent")
    ap.add_argument("--profile", default=None,
                    help="demo profile supplying the sample question (rail|hotel)")
    ap.add_argument("--question", default=None,
                    help="question to ask; defaults to the profile's sample question")
    ap.add_argument("--api-key", default=os.environ.get("A2A_API_KEY", "demo-key"),
                    help="API key presented on the JSON-RPC task path")
    ap.add_argument("--live", action="store_true",
                    help="expect a real model on the far side; warn if the answer came "
                         "from the offline stub engine (the engine is the *server's* "
                         "choice — this flag checks it, it cannot change it)")
    args = ap.parse_args(argv)

    profile = load_profile(args.profile)
    question = args.question or profile["sample_question"]

    try:
        result = asyncio.run(
            ask(question, base_url=args.url.rstrip("/"), api_key=args.api_key)
        )
    except keys.SignatureVerificationError as e:
        print(f"card rejected: {type(e).__name__}: {e}", file=sys.stderr)
        return TASK_FAILED_EXIT

    if result["failed"]:
        print(f"task failed: {result['reason']}", file=sys.stderr)
        line = last_audit_line()
        if line:
            print(line)
        return TASK_FAILED_EXIT

    print(f"answer: {result['text']}")
    print(f"grounded: {str(result['metadata'].get('grounded', False)).lower()}")
    line = last_audit_line()
    if line:
        print(line)
        if args.live and " engine=stub " in f" {line} ":
            print(
                "warning: --live was requested but the answer came from the stub "
                "engine; start the server with INTERCHANGE_ENGINE=api or "
                "claude-code to use a real model.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
