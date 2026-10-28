# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, transport-independent snapshot of strict enforcement."""

from dataclasses import dataclass
import json
import math


@dataclass(frozen=True)
class StrictState:
    mode: str
    stage: str
    posture: str | None
    target_height: float | None

    def __post_init__(self) -> None:
        if self.mode not in ("off", "standing", "sitting", "both"):
            raise ValueError("invalid strict mode")
        if self.stage not in ("released", "pending", "arrived"):
            raise ValueError("invalid strict stage")
        if self.stage == "released":
            if self.posture is not None or self.target_height is not None:
                raise ValueError("released state cannot have a target")
        elif (self.posture not in ("sitting", "standing")
              or isinstance(self.target_height, bool)
              or not isinstance(self.target_height, (int, float))
              or not math.isfinite(self.target_height)):
            raise ValueError("invalid strict target")

    def to_json(self) -> str:
        return json.dumps({"mode": self.mode, "stage": self.stage,
                           "posture": self.posture, "target_height": self.target_height},
                          allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> "StrictState":
        obj = json.loads(payload)
        if not isinstance(obj, dict) or set(obj) != {"mode", "stage", "posture", "target_height"}:
            raise ValueError("invalid strict snapshot")
        return cls(**obj)
