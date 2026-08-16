from __future__ import annotations

from app.domain.contracts import CapabilityDescriptor
from app.domain.contracts.common import JsonValue

from .contracts import RegisteredCapabilityView


def project_capability(view: RegisteredCapabilityView) -> CapabilityDescriptor | None:
    if not view.permitted_operations:
        return None
    attributes: JsonValue = {
        "schema_id": "plugin.capability.attributes.v1",
        "plugin_id": view.plugin_id,
        "plugin_generation": view.plugin_generation,
        "plugin_version": view.plugin_version,
        "contract_version": view.contract_version,
        "operations": tuple(
            {
                "operation_id": operation.operation_id,
                "input_schema_ref": operation.input_schema_ref,
                "output_schema_ref": operation.output_schema_ref,
                "side_effect_class": operation.side_effect_class.value,
                "cancellation_support": operation.cancellation_support.value,
                "timeout_support": {
                    "supports_deadline": operation.timeout_support.supports_deadline,
                    "supports_provider_timeout": (
                        operation.timeout_support.supports_provider_timeout
                    ),
                },
            }
            for operation in view.permitted_operations
        ),
        "required_permissions": tuple(
            {"permission_id": permission.permission_id, "scope_ref": permission.scope_ref}
            for permission in view.required_permissions
        ),
    }
    return CapabilityDescriptor(
        view.declaration.capability_id,
        view.declaration.capability_type,
        tuple(operation.operation_id for operation in view.permitted_operations),
        view.effective_availability,
        view.capability_revision,
        attributes,
    )
