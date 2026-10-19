"""通常CLIから呼び出す統合Coreの正規構成入口。"""

from __future__ import annotations

import uuid

from app.adapters.llm.connections import production_llm_connection_adapters
from app.bootstrap.core_application import CoreApplication
from app.bootstrap.runtime_owners import CoreRuntimeOwners, default_core_runtime_owners
from app.bootstrap.speech_production_configuration import SpeechProductionInputs
from app.bootstrap.system_cognition_configuration import ROOT, CoreRunIdentity, build_core
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.config.layered import ConfigurationError, load_user_configuration
from app.infrastructure.scheduling import SystemRuntimeClock


def _new_core_run_identity() -> CoreRunIdentity:
    """本体の一回の起動へ、新しい実行識別子を与える。"""
    return CoreRunIdentity(
        f"core-epoch-{uuid.uuid4().hex}",
        f"core-run-{uuid.uuid4().hex}",
    )


def _load_core_speech(
    run: CoreRunIdentity,
    owners: CoreRuntimeOwners,
) -> SpeechProductionInputs | None:
    """三層設定のSpeech有効化だけを既存登録済みOwnerへ接続する。"""
    root = ROOT / "config"
    try:
        configuration = load_user_configuration(root)
        if configuration.speech is None:
            return None
        if owners.speech is None:
            raise ValueError("Speech本番接続が登録されていません")
        from app.bootstrap.speech_deployment import create_speech_deployment

        source = create_speech_deployment(
            root,
            run=run,
            semantic_owner=owners.speech.semantic_owner,
            memory=owners.speech.memory,
            registry=owners.speech.registry,
        )
        if source is None:
            raise ValueError("Speech設定の状態が一致しません")
        return source.inputs
    except ConfigurationError:
        raise ValueError("Speech本番設定または登録を使用できません") from None


async def build_core_application(
    owners: CoreRuntimeOwners | None = None,
) -> CoreApplication:
    """通常CLIが使用する本体構成を、既存公開factoryだけで組み立てる。"""
    runtime_owners = owners if owners is not None else default_core_runtime_owners()
    if runtime_owners.memory is None:
        # MemoryはSpeechの有効設定とは独立した本体必須Owner。
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    run = _new_core_run_identity()
    speech = _load_core_speech(run, runtime_owners)
    return await build_core(
        run_identity=run,
        activation_id="yura.core.explicit",
        fresh_start=True,
        clock=SystemRuntimeClock(),
        registry=runtime_owners.registry,
        precondition_router=runtime_owners.precondition_router,
        precondition_bindings=runtime_owners.precondition_bindings,
        activity_bindings=runtime_owners.activity_bindings,
        fast_rules=runtime_owners.fast_rules,
        llm_adapters=production_llm_connection_adapters(),
        speech=speech,
        memory=runtime_owners.memory,
    )
