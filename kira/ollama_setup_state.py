"""Explicit, independently observable Ollama setup lifecycle states."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
class SetupStage(str, Enum):
    INSTALLATION="installation"
    SERVICE="service"
    CONNECTION="connection"
    VERSION="version"
    MODEL_CATALOG="model_catalog"
    SELECTED_MODEL="selected_model"
    INFERENCE="inference"
class StageStatus(str, Enum):
    UNKNOWN="unknown"
    READY="ready"
    MISSING="missing"
    STOPPED="stopped"
    UNREACHABLE="unreachable"
    UNAVAILABLE="unavailable"
    FAILED="failed"
    NOT_CONFIGURED="not_configured"
    NOT_TESTED="not_tested"
@dataclass(frozen=True)
class StageObservation:
    status: StageStatus=StageStatus.UNKNOWN
    error: str|None=None
class OllamaSetupStateMachine:
    """Own the observed state of each setup stage without collapsing failures."""
    def __init__(self):
        self._stages={stage:StageObservation() for stage in SetupStage}
    def transition(self,stage,status,error=None):
        key=stage if isinstance(stage,SetupStage) else SetupStage(str(stage))
        value=status if isinstance(status,StageStatus) else StageStatus(str(status))
        self._stages[key]=StageObservation(value,str(error) if error else None)
    def observation(self,stage):
        key=stage if isinstance(stage,SetupStage) else SetupStage(str(stage))
        return self._stages[key]
    def snapshot(self):
        return {stage.value:{"status":item.status.value,"error":item.error}
                for stage,item in self._stages.items()}
    @property
    def ready(self):
        required=(SetupStage.CONNECTION,SetupStage.VERSION,SetupStage.MODEL_CATALOG,
                  SetupStage.SELECTED_MODEL,SetupStage.INFERENCE)
        return all(self._stages[stage].status is StageStatus.READY for stage in required)
