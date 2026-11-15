import platform
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EnvironmentRecord:
    os_name: str
    os_version: str
    python_version: str
    machine: str

    @classmethod
    def capture(cls) -> "EnvironmentRecord":
        return cls(
            os_name=platform.system(),
            os_version=platform.version(),
            python_version=sys.version,
            machine=platform.machine(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
