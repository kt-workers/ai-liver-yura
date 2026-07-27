from unittest.mock import MagicMock

import pytest

from app.runtime.runtime_coordinator import RuntimeCoordinator

pytestmark = pytest.mark.unit


def test_pending_confirmation_falls_back_to_manager_without_coordinator() -> None:
    pending = MagicMock()
    manager = MagicMock()
    manager.current.return_value = pending
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator._confirmation_coordinator = None
    coordinator._pending_confirmation_manager = manager

    assert coordinator.pending_confirmation is pending
    manager.current.assert_called_once_with()


def test_pending_confirmation_prefers_confirmation_coordinator() -> None:
    pending = MagicMock()
    confirmation_coordinator = MagicMock(pending=pending)
    manager = MagicMock()
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator._confirmation_coordinator = confirmation_coordinator
    coordinator._pending_confirmation_manager = manager

    assert coordinator.pending_confirmation is pending
    manager.current.assert_not_called()
