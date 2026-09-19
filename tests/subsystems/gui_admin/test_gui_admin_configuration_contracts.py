from __future__ import annotations

from typing import cast

import pytest

from app.domain.contracts.common import thaw_json
from app.subsystems.gui_admin import (
    GuiAdminAccessContext,
    GuiAdminAccessLevel,
    GuiAdminConfigurationMutationRequest,
    GuiAdminConfigurationReadModel,
    GuiAdminEditableConfigurationField,
    GuiAdminSecretFieldStatus,
)


def test_configuration_read_model_is_immutable_and_never_projects_secret_values() -> None:
    values = {"model": "safe-model"}
    model = GuiAdminConfigurationReadModel(
        "owner:llm", 1, 4,
        (GuiAdminEditableConfigurationField("model", "string", True, False),
         GuiAdminEditableConfigurationField("api_key", "secret", True, True)),
        values, {"source": "owner:llm"},
        (GuiAdminSecretFieldStatus("api_key", True),),
    )
    values["model"] = "changed"
    assert thaw_json(model.effective_values) == {"model": "safe-model"}
    assert "never-project" not in repr(model)
    with pytest.raises(ValueError):
        GuiAdminConfigurationReadModel(
            "owner:llm", 1, 4, model.editable_fields,
            {"api_key": "never-project"}, {}, model.secret_fields,
        )


def test_configuration_contract_rejects_invalid_metadata_and_mutation_without_access() -> None:
    with pytest.raises(ValueError):
        GuiAdminEditableConfigurationField("field", "string", True, cast(bool, 1))
    with pytest.raises(ValueError):
        GuiAdminConfigurationMutationRequest(
            "owner:llm", 1, 4,
            GuiAdminAccessContext(GuiAdminAccessLevel.OPERATOR_READ), {"model": "x"},
        )
    assert GuiAdminAccessContext(GuiAdminAccessLevel.DEVELOPMENT_VALIDATION).may_mutate is False
    assert GuiAdminAccessContext(GuiAdminAccessLevel.OPERATOR_MUTATION).may_mutate is True
