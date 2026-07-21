import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from queue import Full, Queue
import threading
import time
from typing import TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelProvider,
    ModelStreamChunk,
    ToolExecutor,
)
from peon.app.coding_session import (
    MessageEvent,
    RunLimits,
    SessionEvent,
    StopReason,
    StreamDeltaEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from peon.app.resources import ResourceInventory
from peon.app.session_controller import PromptIntent, SessionController
from peon.app.sessions import MemorySessionStore, SessionStore

SessionEventHandler: TypeAlias = Callable[[SessionEvent], None]


class BoundedEventQueue:
    """Bounded, thread-safe queue that coalesces delta events under backpressure."""

    def __init__(self, maxsize: int = 100) -> None:
        self.maxsize = maxsize
        self._queue: Queue[SessionEvent | None] = Queue(maxsize=maxsize)
        self._lock = threading.Lock()

    def put(self, event: SessionEvent | None) -> None:
        if event is None:
            self._queue.put(None)
            return

        with self._lock:
            try:
                self._queue.put_nowait(event)
            except Full:
                self._queue.put(event)

    def get(self, timeout: float | None = None) -> SessionEvent | None:
        try:
            return self._queue.get(timeout=timeout)
        except Exception:
            return None


class EmbeddedSession:
    """Submit text prompts without starting a terminal presentation host."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        context: AgentContext | None = None,
        tools: ToolExecutor | None = None,
        model: str | None = None,
        resources: ResourceInventory | None = None,
        on_event: SessionEventHandler | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
        limits: RunLimits | None = None,
    ) -> None:
        active_store = session_store or MemorySessionStore()
        active_session_id = session_id
        if active_session_id is None:
            active_session_id = active_store.create().session_id
        self._controller = SessionController(
            provider=provider,
            session_store=active_store,
            session_id=active_session_id,
            run_id=run_id,
            context=context,
            executor=tools,
            model=model,
            resources=resources,
            on_event=on_event,
            clock=clock,
            id_factory=id_factory,
            limits=limits,
        )

    @property
    def session_id(self) -> str:
        return self._controller.session_id

    @property
    def run_id(self) -> str:
        return self._controller.run_id

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._controller.messages

    def submit(self, text: str) -> TurnResult:
        """Submit one text prompt and return its structured turn result."""
        return self._controller.dispatch(PromptIntent(text))

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._controller.cancel()

    def iter_events(
        self,
        text: str,
        *,
        max_buffer_size: int = 100,
    ) -> Iterator[SessionEvent]:
        """Submit text prompt and yield live events synchronously with a bounded queue."""
        event_queue = BoundedEventQueue(maxsize=max_buffer_size)

        def _on_event(event: SessionEvent) -> None:
            event_queue.put(event)

        sub_session = EmbeddedSession(
            provider=self._controller.provider,
            session_store=self._controller.session_store,
            session_id=self.session_id,
            run_id=self.run_id,
            context=self._controller._context,
            tools=self._controller._executor,
            model=self._controller._model,
            resources=self._controller._resources,
            on_event=_on_event,
            limits=self._controller._limits,
        )

        def _worker() -> None:
            try:
                sub_session.submit(text)
            finally:
                event_queue.put(None)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            while True:
                item = event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            sub_session.cancel()
            thread.join(timeout=1.0)

    async def aiter_events(
        self,
        text: str,
        *,
        max_buffer_size: int = 100,
    ) -> AsyncIterator[SessionEvent]:
        """Submit text prompt and yield live events asynchronously off the main thread."""
        loop = asyncio.get_running_loop()
        event_queue = BoundedEventQueue(maxsize=max_buffer_size)

        def _on_event(event: SessionEvent) -> None:
            event_queue.put(event)

        sub_session = EmbeddedSession(
            provider=self._controller.provider,
            session_store=self._controller.session_store,
            session_id=self.session_id,
            run_id=self.run_id,
            context=self._controller._context,
            tools=self._controller._executor,
            model=self._controller._model,
            resources=self._controller._resources,
            on_event=_on_event,
            limits=self._controller._limits,
        )

        def _worker() -> None:
            try:
                sub_session.submit(text)
            finally:
                event_queue.put(None)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            while True:
                item = await loop.run_in_executor(None, event_queue.get, 0.05)
                if item is None:
                    break
                yield item
        except asyncio.CancelledError:
            sub_session.cancel()
            raise
        finally:
            sub_session.cancel()
            await loop.run_in_executor(None, thread.join, 1.0)


__all__ = [
    "BoundedEventQueue",
    "EmbeddedSession",
    "MessageEvent",
    "SessionEvent",
    "StreamDeltaEvent",
    "TurnFinishedEvent",
    "TurnResult",
    "TurnStartedEvent",
]