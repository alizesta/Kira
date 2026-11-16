"""Application composition and lifecycle infrastructure."""

from .module_manager import ModuleManager, ModuleManagerError, ModuleState

__all__ = ["ModuleManager", "ModuleManagerError", "ModuleState"]
