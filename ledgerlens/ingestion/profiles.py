from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ledgerlens.domain import MappingProfile


def load_mapping_profile(path: str | Path) -> MappingProfile:
    profile_path = Path(path)
    raw = profile_path.read_text(encoding="utf-8")
    data = _parse_profile(raw, profile_path.suffix.lower())
    return MappingProfile(
        client_id=data["client_id"],
        profile_name=data.get("profile_name", data.get("name", profile_path.stem)),
        source_system=data["source_system"],
        account_id=data["account_id"],
        file_type=data.get("file_type", "csv"),
        default_currency=data.get("default_currency", data.get("currency", "USD")),
        amount_strategy=data.get("amount_strategy", "signed_amount"),
        column_map=data.get("column_map", data.get("columns", {})),
        date_formats=data.get("date_formats", ["%Y-%m-%d", "%m/%d/%Y"]),
        debit_is_negative=bool(data.get("debit_is_negative", True)),
        amount_tolerance=str(data.get("amount_tolerance", "0.00")),
        date_window_days=int(data.get("date_window_days", 3)),
        required_fields=list(data.get("required_fields", [])),
        reference_patterns=list(data.get("reference_patterns", [])),
        description_stopwords=list(data.get("description_stopwords", [])),
    )


def _parse_profile(raw: str, suffix: str) -> dict[str, Any]:
    if suffix == ".json":
        return json.loads(raw)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError as exc:
            raise RuntimeError("YAML profiles require PyYAML; use JSON for stdlib-only runs") from exc
        return yaml.safe_load(raw)
    raise ValueError(f"unsupported mapping profile format: {suffix}")
