"""ゆら本体の標準CLI起動・停止と移行期間の公開互換入口。"""

from __future__ import annotations

import asyncio
import signal
import sys

from app.bootstrap.cli_composition import build_core_application as build_core_application
from app.bootstrap.core_components import CoreComponents as CoreComponents
from app.bootstrap.runtime_assembly import _compose_core as _compose_core
from app.bootstrap.runtime_assembly import _load_core as _load_core
from app.bootstrap.runtime_assembly import build_core_runtime as build_core_runtime
from app.bootstrap.runtime_assembly import build_persistent_core as build_persistent_core
from app.bootstrap.runtime_owners import CoreRuntimeOwners as CoreRuntimeOwners
from app.bootstrap.runtime_owners import CoreSpeechOwners as CoreSpeechOwners
from app.bootstrap.runtime_owners import default_core_runtime_owners as default_core_runtime_owners
from app.bootstrap.system_cognition_configuration import CoreApplication as CoreApplication
from app.bootstrap.system_cognition_configuration import CoreRunIdentity as CoreRunIdentity
from app.bootstrap.system_cognition_configuration import build_core as build_core
from app.config.core_contracts import CoreConfigurationError
from app.usecases.brain_input_meaning import InputMeaningBrainModulePort as InputMeaningBrainModulePort
from app.usecases.brain_input_meaning import InputMeaningBrainWorkPayload as InputMeaningBrainWorkPayload
from app.usecases.brain_input_meaning import UnavailableInputMeaningLiveContextPort as UnavailableInputMeaningLiveContextPort
from app.usecases.core_lifecycle import start_core as start_core
from app.usecases.core_lifecycle import stop_core as stop_core

async def run_core_runtime() -> None:
    """旧呼出しは唯一の正式Core起動へ委譲する。"""
    await run_core()



async def run_core() -> None:
    """本体を開始し、停止通知まで所有資源を保持する。"""
    app = await build_core_application()
    loop = asyncio.get_running_loop()
    stop_requested = asyncio.Event()
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    registered: list[signal.Signals] = []
    try:
        for signum in previous:
            loop.add_signal_handler(signum, stop_requested.set)
            registered.append(signum)
        await app.start()
        print("ゆら本体の起動が完了しました。", flush=True)
        await stop_requested.wait()
    finally:
        try:
            await app.stop()
        finally:
            for signum in registered:
                loop.remove_signal_handler(signum)
                signal.signal(signum, previous[signum])


def main() -> None:
    arguments = tuple(sys.argv[1:])
    if arguments:
        print("使用方法: python -m app", file=sys.stderr)
        raise SystemExit(2)
    try:
        asyncio.run(run_core())
    except CoreConfigurationError as error:
        print(
            f"ゆら本体の構成、起動または停止に失敗しました: {error.code.value}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (OSError, ValueError, RuntimeError):
        print("ゆら本体の構成、起動または停止に失敗しました。", file=sys.stderr)
        raise SystemExit(1) from None
