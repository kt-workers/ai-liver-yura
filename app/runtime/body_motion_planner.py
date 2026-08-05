from __future__ import annotations

from uuid import uuid4

from app.domain.body_motion import (
    BodyMotionOperation,
    BodyMotionPlan,
    BodyMotionRequest,
)


class BodyMotionPlanner:
    """運動要求を、骨格能力を検証した実行計画へ変換する。

    完成モーション名は扱わず、Canonical joint／end effectorと運動プリミティブ
    だけを検証する。
    """

    SUPPORTED_TARGETS = frozenset(
        {
            "root",
            "pelvis",
            "spine",
            "chest",
            "neck",
            "head",
            "left_shoulder",
            "left_elbow",
            "left_hand",
            "right_shoulder",
            "right_elbow",
            "right_hand",
            "left_hip",
            "left_knee",
            "left_ankle",
            "right_hip",
            "right_knee",
            "right_ankle",
        }
    )

    DEFAULT_PIVOTS = {
        "left_hand": "left_shoulder",
        "left_elbow": "left_shoulder",
        "right_hand": "right_shoulder",
        "right_elbow": "right_shoulder",
        "left_ankle": "left_hip",
        "left_knee": "left_hip",
        "right_ankle": "right_hip",
        "right_knee": "right_hip",
        "head": "neck",
        "neck": "chest",
        "chest": "pelvis",
    }

    def compile(self, request: BodyMotionRequest) -> BodyMotionPlan:
        self._validate_request(request)
        plan_id = request.motion_id or f"body-motion-{uuid4()}"
        return BodyMotionPlan(
            plan_id=plan_id,
            root=request,
            duration_seconds=self._duration(request),
            targets=self._targets(request),
        )

    def default_pivot(self, target: str) -> str | None:
        return self.DEFAULT_PIVOTS.get(target)

    def _validate_request(self, request: BodyMotionRequest) -> None:
        if request.target is not None and request.target not in self.SUPPORTED_TARGETS:
            raise ValueError(f"unsupported body motion target: {request.target}")
        if request.pivot is not None and request.pivot not in self.SUPPORTED_TARGETS:
            raise ValueError(f"unsupported body motion pivot: {request.pivot}")
        if request.operation in {
            BodyMotionOperation.SEQUENCE,
            BodyMotionOperation.PARALLEL,
            BodyMotionOperation.REPEAT,
        }:
            for child in request.children:
                self._validate_request(child)
        if request.operation in {
            BodyMotionOperation.CIRCLE,
            BodyMotionOperation.ROTATE,
        }:
            target = request.target
            if target is not None and request.pivot is None:
                if self.default_pivot(target) is None:
                    raise ValueError(
                        f"{request.operation.value} requires pivot for target {target}"
                    )

    def _duration(self, request: BodyMotionRequest) -> float:
        if request.operation in {
            BodyMotionOperation.HOLD,
            BodyMotionOperation.RELEASE,
        }:
            return 0.0
        if request.operation is BodyMotionOperation.SEQUENCE:
            return request.timing.delay_seconds + sum(
                self._duration(child) for child in request.children
            )
        if request.operation is BodyMotionOperation.PARALLEL:
            return request.timing.delay_seconds + max(
                self._duration(child) for child in request.children
            )
        if request.operation is BodyMotionOperation.REPEAT:
            child_duration = self._duration(request.children[0])
            return request.timing.delay_seconds + (
                child_duration * request.timing.repetitions
            )
        return request.timing.total_seconds

    def _targets(self, request: BodyMotionRequest) -> tuple[str, ...]:
        result: list[str] = []
        if request.target is not None:
            result.append(request.target)
        if request.pivot is not None:
            result.append(request.pivot)
        for child in request.children:
            result.extend(self._targets(child))
        return tuple(dict.fromkeys(result))
