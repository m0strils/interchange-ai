"""The Interchange knowledge agent's A2A server surface (ADR-0013).

Three pieces, in the order a caller meets them:

1. **The Agent Card** (``build_agent_card``) — served unauthenticated at
   ``/.well-known/agent-card.json``, because discovery has to work before anyone
   has a key. Signed (JWS/ES256 over the RFC 8785 canonical form) so the caller
   can tell this agent from something imitating it. It advertises two JSON-RPC
   interfaces, 1.0 and 0.3, at the same URL: 1.0 is the current spec, 0.3 is what
   watsonx Orchestrate registers external A2A agents against today.
2. **The API-key gate** (``ApiKeyMiddleware``) — everything under ``/a2a`` needs a
   key, compared in constant time and mapped to a *caller label*. The key itself
   never reaches the audit log; the label does.
3. **The executor** (``InterchangeExecutor``) — task-based only: submit, start
   work, emit the answer as an artifact, complete. A2A is a new transport into
   the same guarded core, not a second code path around it: every task goes
   through ``interchange.answer_detail``, so the input guardrail, the grounding
   check and the audit row are exactly the ones the CLI and the REST surface get.

``mount_a2a(app, base_url)`` bolts all three onto an existing FastAPI app.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    APIKeySecurityScheme,
    Part,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import (
    PROTOCOL_VERSION_0_3,
    PROTOCOL_VERSION_1_0,
    TransportProtocol,
)
from a2a.utils.signing import create_agent_card_signer

import enterprise
import interchange
from a2a_agent import keys
from a2a_agent.profiles import load_profile

logger = logging.getLogger(__name__)

#: Path the JSON-RPC task surface is mounted at (and the prefix the key gate guards).
RPC_PATH = "/a2a"
#: Header carrying the caller's API key. Configurable because Orchestrate's
#: API_KEY scheme header name is a per-tenant setting.
API_KEY_HEADER_ENV = "A2A_API_KEY_HEADER"
DEFAULT_API_KEY_HEADER = "X-API-Key"
#: ``"<key>:<label>,<key2>:<label2>"`` — the key is the secret, the label is what
#: lands in the audit row.
API_KEYS_ENV = "A2A_API_KEYS"
UNKNOWN_CALLER = "unknown"
SECURITY_SCHEME_ID = "apiKey"
SKILL_ID = "policy-qa"
AGENT_VERSION = "1.0.0"


# --- identity: the Agent Card ---------------------------------------------
def api_key_header() -> str:
    """The header name this deployment expects the API key in."""
    return os.environ.get(API_KEY_HEADER_ENV) or DEFAULT_API_KEY_HEADER


def api_key_labels() -> dict[str, str]:
    """``{api key: caller label}`` parsed from the environment.

    Empty when unset, which means *no key is valid* — a deployment that forgot
    to configure keys refuses tasks rather than serving them to anyone.
    """
    raw = os.environ.get(API_KEYS_ENV, "")
    labels: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        key, _, label = pair.partition(":")
        key, label = key.strip(), label.strip()
        if key:
            labels[key] = label or UNKNOWN_CALLER
    return labels


def caller_label(api_key: str | None) -> str:
    """Map a presented key to its caller label, in constant time.

    Every configured key is compared even after a match, so the number of
    comparisons does not depend on which key was presented.
    """
    label = UNKNOWN_CALLER
    for known, known_label in api_key_labels().items():
        if api_key is not None and hmac.compare_digest(api_key, known):
            label = known_label
    return label


def build_agent_card(base_url: str, profile: dict) -> AgentCard:
    """The capability description this agent publishes, for one demo profile.

    Honest-card rule: it advertises exactly what exists — one skill, streaming
    on (the executor really does emit task events), push notifications absent
    because they are not built (ADR-0013 "deferred, explicitly").
    """
    rpc_url = f"{base_url.rstrip('/')}{RPC_PATH}"
    header = api_key_header()
    sample = profile.get("sample_question", "")
    return AgentCard(
        name=profile.get("knowledge_agent_name", "interchange-knowledge"),
        description=(profile.get("description") or "").strip(),
        version=AGENT_VERSION,
        # Same endpoint, two protocol versions: 1.0 for spec-current clients,
        # 0.3 for watsonx Orchestrate's external-agent registration flow.
        supported_interfaces=[
            AgentInterface(
                url=rpc_url,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            ),
            AgentInterface(
                url=rpc_url,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_0_3,
            ),
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name=SKILL_ID,
                description=(
                    "Answer a question from the indexed corpus and return a cited, "
                    "grounding-checked answer. Blocked by the input guardrail if the "
                    "question looks like a prompt-injection attempt."
                ),
                tags=["knowledge", "rag", "grounded", profile.get("name", "")],
                examples=[sample] if sample else [],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
        security_schemes={
            SECURITY_SCHEME_ID: SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    location="header",
                    name=header,
                    description="Per-caller API key; identifies the caller in the audit log.",
                )
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={SECURITY_SCHEME_ID: StringList(list=[])})
        ],
    )


# --- the guarded work ------------------------------------------------------
def _answer_as(label: str, question: str, collection: str | None = None) -> dict:
    """Run the governed pipeline attributed to ``a2a:<label>``.

    Runs on a worker thread (the pipeline is blocking), so CALLER is set *inside*
    the thread: ``asyncio.to_thread`` copies the context, but setting it here
    means the attribution is right no matter how the call is scheduled.

    ``collection`` is this agent's profile corpus (``profiles.yaml``), passed
    through to ``answer_detail`` so a hotel-profile agent reads the hotel corpus
    even when ``INTERCHANGE_COLLECTION`` was never re-exported for this process
    (e.g. two profiles mounted in the same test process).
    """
    token = enterprise.CALLER.set(f"a2a:{label}")
    try:
        # ADR-0018: pass mode/context as None so answer_detail's single resolver reads
        # this collection's profile (retrieval mode AND context settings alike) — closing
        # the old mismatch where A2A ignored the profile's mode and always ran hybrid.
        return interchange.answer_detail(
            question,
            engine=os.environ.get("INTERCHANGE_ENGINE", "api"),
            collection=collection,
            mode=None,
            context=None,
        )
    finally:
        enterprise.CALLER.reset(token)


class InterchangeExecutor(AgentExecutor):
    """Turns an A2A task into one governed ``answer_detail`` call.

    Task-based only — submit, start work, artifact, terminal state — never a bare
    ``Message``. Mixing the two shapes in one response is what the SDK's executor
    contract forbids, and a task is what a peer agent can actually track.

    A guardrail block is a *failed task*, not an exception and not a cheerful
    answer: the caller is told the request was refused, and the audit row already
    carries the block reason.
    """

    def __init__(self, collection: str | None = None) -> None:
        #: this agent's profile corpus (``profiles.yaml`` ``collection:``),
        #: bound at mount time so the vertical is data, not code.
        self._collection = collection

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # The submitted Task object itself is the first event: the 1.1 runtime
        # rejects a status update for a task it has never seen
        # ("Agent should enqueue Task before TaskStatusUpdateEvent"), so this
        # stands in for the TaskUpdater.submit() the plan described.
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()

        question = context.get_user_input()
        headers = context.call_context.state.get("headers", {}) or {}
        label = caller_label(headers.get(api_key_header().lower()))

        detail = await asyncio.to_thread(_answer_as, label, question, self._collection)

        if detail["blocked"]:
            await updater.failed(
                updater.new_agent_message([Part(text=detail["text"])])
            )
            return

        await updater.add_artifact(
            [Part(text=detail["text"])],
            name="answer",
            metadata={
                "grounded": detail["grounded"],
                "sources": list(detail["sources"]),
                "engine": detail["engine"],
                "model": detail["model"],
                "cost_usd": detail["cost_usd"],
                "telemetry": detail["telemetry"],
            },
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """One question, one round trip — there is nothing long-running to cancel."""
        task = context.current_task
        task_id = task.id if task else context.task_id
        context_id = task.context_id if task else context.context_id
        await TaskUpdater(event_queue, task_id, context_id).cancel()


# --- the API-key gate ------------------------------------------------------
class ApiKeyMiddleware:
    """Require a valid API key on ``/a2a``; leave the card endpoint open.

    Written as raw ASGI rather than ``BaseHTTPMiddleware`` on purpose: the task
    surface streams task events over SSE, and ``BaseHTTPMiddleware`` buffers
    streaming responses. This one touches the scope and gets out of the way.
    """

    def __init__(self, app, protected_prefix: str = RPC_PATH):
        self.app = app
        self.protected_prefix = protected_prefix

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").startswith(
            self.protected_prefix
        ):
            header = api_key_header().lower().encode()
            presented = None
            for name, value in scope.get("headers", []):
                if name.lower() == header:
                    presented = value.decode("latin-1")
                    break
            if caller_label(presented) == UNKNOWN_CALLER:
                from starlette.responses import JSONResponse

                response = JSONResponse(
                    {
                        "error": "unauthorized",
                        "detail": f"a valid {api_key_header()} header is required "
                                  f"for {self.protected_prefix}",
                    },
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# --- mounting --------------------------------------------------------------
def _signed_card_modifier(card: AgentCard):
    """An async card modifier that signs a fresh copy of the card per request.

    Fresh copy because ``create_agent_card_signer`` *appends* to
    ``card.signatures``; signing the shared card in place would grow a new
    signature on every fetch.
    """
    private_pem = keys.load_private_key_pem()
    if not private_pem:
        logger.warning(
            "%s is not set: serving an UNSIGNED Agent Card. A client with a pinned "
            "key will refuse it (NoSignatureError), which is the correct outcome.",
            keys.PRIVATE_KEY_ENV,
        )
        return None

    signer = create_agent_card_signer(
        private_pem, {"alg": "ES256", "kid": keys.active_kid()}
    )

    async def card_modifier(to_serve: AgentCard) -> AgentCard:
        fresh = AgentCard()
        fresh.CopyFrom(to_serve)
        del fresh.signatures[:]
        return signer(fresh)

    return card_modifier


def mount_a2a(app, base_url: str, profile: dict | None = None) -> AgentCard:
    """Add the A2A card + task routes (and the key gate) to a FastAPI app.

    Returns the card so a caller can inspect what was published.
    """
    profile = profile or load_profile()
    card = build_agent_card(base_url, profile)

    handler = DefaultRequestHandler(
        agent_executor=InterchangeExecutor(collection=profile.get("collection")),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    # Discovery stays open; the task surface is behind the key gate.
    app.routes.extend(
        create_agent_card_routes(card, card_modifier=_signed_card_modifier(card))
    )
    app.routes.extend(
        create_jsonrpc_routes(handler, rpc_url=RPC_PATH, enable_v0_3_compat=True)
    )
    app.add_middleware(ApiKeyMiddleware)
    return card
