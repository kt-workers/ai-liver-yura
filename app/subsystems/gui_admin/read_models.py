from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.domain.contracts.common import require_identifier

from .contracts import AdminReadModelEnvelope, GuiAdminOperationalPolicy, GuiAdminReadModelKind

ReadModelKey = tuple[GuiAdminReadModelKind, str]


@dataclass(frozen=True, slots=True)
class GuiAdminReadModelSubscription:
    subscription_id: str
    client_id: str
    model_kind: GuiAdminReadModelKind
    source_owner: str
    policy_id: str
    policy_revision: int


@dataclass(frozen=True, slots=True)
class GuiAdminReadModelUpdateBatch:
    client_id: str
    updates: tuple[AdminReadModelEnvelope, ...]
    resync_required: bool
    rejected_update_count: int
    policy_id: str
    policy_revision: int


@dataclass(slots=True)
class _ClientState:
    subscriptions: dict[str, ReadModelKey] = field(default_factory=dict)
    pending: dict[ReadModelKey, AdminReadModelEnvelope] = field(default_factory=dict)
    resync_required: bool = False
    rejected_update_count: int = 0


class GuiAdminReadModelBroker:
    def __init__(self, policy: GuiAdminOperationalPolicy | None = None) -> None:
        self._policy = policy or GuiAdminOperationalPolicy()
        self._latest: dict[ReadModelKey, AdminReadModelEnvelope] = {}
        self._clients: dict[str, _ClientState] = {}

    @property
    def policy(self) -> GuiAdminOperationalPolicy:
        return self._policy

    def latest(
        self, model_kind: GuiAdminReadModelKind, source_owner: str
    ) -> AdminReadModelEnvelope | None:
        if not isinstance(model_kind, GuiAdminReadModelKind):
            raise ValueError("model_kind が不正です")
        require_identifier(source_owner, "source_owner")
        return self._latest.get((model_kind, source_owner))

    def publish(self, envelope: AdminReadModelEnvelope) -> None:
        if not isinstance(envelope, AdminReadModelEnvelope):
            raise ValueError("envelope が不正です")
        if envelope.payload_size_bytes > self._policy.max_read_model_payload_bytes:
            raise ValueError("Read Model payloadが運用上限を超えています")

        key = envelope.identity
        current = self._latest.get(key)
        if current is not None:
            if envelope.source_revision < current.source_revision:
                raise ValueError("古いsource_revisionのRead Modelは公開できません")
            if envelope.source_revision == current.source_revision:
                if envelope != current:
                    raise ValueError("同一source_revisionで内容が競合しています")
                return

        self._latest[key] = envelope
        for state in self._clients.values():
            if key in state.subscriptions.values():
                self._offer(state, key, envelope)

    def subscribe(
        self,
        *,
        client_id: str,
        subscription_id: str,
        model_kind: GuiAdminReadModelKind,
        source_owner: str,
    ) -> GuiAdminReadModelSubscription:
        require_identifier(client_id, "client_id")
        require_identifier(subscription_id, "subscription_id")
        if not isinstance(model_kind, GuiAdminReadModelKind):
            raise ValueError("model_kind が不正です")
        require_identifier(source_owner, "source_owner")

        state = self._clients.setdefault(client_id, _ClientState())
        if subscription_id in state.subscriptions:
            raise ValueError("subscription_id はclient内で一意でなければなりません")
        key = (model_kind, source_owner)
        if key in state.subscriptions.values():
            raise ValueError("同一Read Modelへの重複subscriptionは作成できません")
        if len(state.subscriptions) >= self._policy.max_active_subscriptions_per_client:
            raise ValueError("active subscription数が運用上限を超えています")

        state.subscriptions[subscription_id] = key
        latest = self._latest.get(key)
        if latest is not None:
            self._offer(state, key, latest)
        return GuiAdminReadModelSubscription(
            subscription_id=subscription_id,
            client_id=client_id,
            model_kind=model_kind,
            source_owner=source_owner,
            policy_id=self._policy.policy_id,
            policy_revision=self._policy.policy_revision,
        )

    def unsubscribe(self, *, client_id: str, subscription_id: str) -> None:
        require_identifier(client_id, "client_id")
        require_identifier(subscription_id, "subscription_id")
        state = self._clients.get(client_id)
        if state is None:
            return
        key = state.subscriptions.pop(subscription_id, None)
        if key is not None:
            state.pending.pop(key, None)
        if not state.subscriptions:
            self._clients.pop(client_id, None)

    def disconnect(self, client_id: str) -> None:
        require_identifier(client_id, "client_id")
        self._clients.pop(client_id, None)

    def poll(self, client_id: str) -> GuiAdminReadModelUpdateBatch:
        require_identifier(client_id, "client_id")
        state = self._clients.get(client_id)
        if state is None:
            return GuiAdminReadModelUpdateBatch(
                client_id=client_id,
                updates=(),
                resync_required=False,
                rejected_update_count=0,
                policy_id=self._policy.policy_id,
                policy_revision=self._policy.policy_revision,
            )
        updates = self._sorted(state.pending.values())
        batch = GuiAdminReadModelUpdateBatch(
            client_id=client_id,
            updates=updates,
            resync_required=state.resync_required,
            rejected_update_count=state.rejected_update_count,
            policy_id=self._policy.policy_id,
            policy_revision=self._policy.policy_revision,
        )
        state.pending.clear()
        state.resync_required = False
        state.rejected_update_count = 0
        return batch

    def authoritative_snapshot(self, client_id: str) -> tuple[AdminReadModelEnvelope, ...]:
        require_identifier(client_id, "client_id")
        state = self._clients.get(client_id)
        if state is None:
            return ()
        models = (
            self._latest[key]
            for key in set(state.subscriptions.values())
            if key in self._latest
        )
        return self._sorted(models)

    def _offer(
        self,
        state: _ClientState,
        key: ReadModelKey,
        envelope: AdminReadModelEnvelope,
    ) -> None:
        if key in state.pending:
            state.pending[key] = envelope
            return
        if len(state.pending) < self._policy.per_client_update_capacity:
            state.pending[key] = envelope
            return
        state.resync_required = True
        state.rejected_update_count += 1

    @staticmethod
    def _sorted(
        values: Iterable[AdminReadModelEnvelope],
    ) -> tuple[AdminReadModelEnvelope, ...]:
        envelopes = tuple(values)
        return tuple(
            sorted(
                envelopes,
                key=lambda item: (item.model_kind.value, item.source_owner),
            )
        )


__all__ = [
    "GuiAdminReadModelBroker",
    "GuiAdminReadModelSubscription",
    "GuiAdminReadModelUpdateBatch",
]
