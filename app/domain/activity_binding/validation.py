"""意味Ownerが明示選択した束縛だけを照合する。"""

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityDescriptor, CapabilityRequirement

from .authority import ActivityExecutionBindingPublication
from .contracts import canonical

BindingRequest = tuple[str | None, str, str | None, str | None, tuple[CapabilityRequirement, ...]]


def selected_bindings(
    requests: tuple[BindingRequest, ...],
    captured: tuple[ActivityExecutionBindingPublication, ...],
    current: tuple[ActivityExecutionBindingPublication, ...],
    capabilities: tuple[CapabilityDescriptor, ...],
) -> tuple[ActivityExecutionBindingPublication, ...]:
    limit = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_fact_refs
    if len(captured) > limit or len(current) > limit:
        raise ValueError("束縛公開件数が上限を超えています")
    initial = {p.value.binding_id: p for p in captured}
    live = {p.value.binding_id: p for p in current}
    if len(initial) != len(captured) or len(live) != len(current):
        raise ValueError("束縛公開identityが重複しています")
    result = []
    for ref, activity_type, target, operation, requirements in requests:
        if ref is None or ref not in initial or ref not in live:
            raise ValueError("明示された正規binding参照が必要です")
        pub = initial[ref]
        if (
            canonical(pub.value.to_dict()) != canonical(live[ref].value.to_dict())
            or pub.tokens != live[ref].tokens
        ):
            raise ValueError("束縛が判断中に変更されています")
        pub.require_current()
        value = pub.value
        if (
            value.activity_type != activity_type
            or value.target_ref != target
            or (operation is not None and value.operation_ref != operation)
        ):
            raise ValueError("活動と束縛の種類・対象・操作が一致しません")
        matching = [
            c
            for c in capabilities
            if c == pub.descriptor
            and c.capability_id == value.capability_id
            and c.revision == value.capability_revision
            and c.capability_type == value.activity_type
            and value.operation_ref in c.operations
        ]
        if (
            len(matching) != 1
            or not requirements
            or any(
                r.capability_type != activity_type or r.operation != value.operation_ref
                for r in requirements
            )
        ):
            raise ValueError("正本能力要件と束縛の操作が一致しません")
        if pub not in result:
            result.append(pub)
    return tuple(result)


def validate_publications(
    publications: tuple[ActivityExecutionBindingPublication, ...], *, max_count: int, max_bytes: int
) -> None:
    if len(publications) > max_count or len({p.value.binding_id for p in publications}) != len(
        publications
    ):
        raise ValueError("束縛公開の件数超過またはidentity重複です")
    for pub in publications:
        if len(canonical(pub.to_dict()).encode()) > max_bytes:
            raise ValueError("束縛公開payloadが容量上限を超えています")
