"""
SQL type mapping and coercion utilities for Hyper extract generation.
Single source of truth for mapping MSTR / Arrow / IR data types to Tableau Hyper SqlTypes,
coercing raw row values to typed Python objects for Hyper ingestion, and verifying column contracts.
"""

import datetime
from typing import Any, Optional

try:
    from tableauhyperapi import SqlType
except ImportError:
    SqlType = None


def sql_type_for(dtype: str) -> Any:
    """
    Map an IR/MSTR/Arrow data type string to the canonical Tableau Hyper SqlType.
    Defaults to SqlType.text() for unknown types.
    """
    if SqlType is None:
        return "text"

    d = str(dtype or "").strip().lower()
    if d in ("integer", "bigint", "int", "smallint"):
        return SqlType.big_int() if d == "bigint" else SqlType.int()
    if d in ("double", "real", "float", "numeric", "decimal"):
        return SqlType.double()
    if d == "date":
        return SqlType.date()
    if d in ("datetime", "timestamp"):
        return SqlType.timestamp()
    if d == "time":
        return SqlType.time()
    if d in ("bool", "boolean"):
        return SqlType.bool()
    return SqlType.text()


def coerce_dim_value(dt: str, val: Any) -> Any:
    """
    Coerce a raw dimension value into the typed Python object required by Hyper Inserter.
    Returns None for missing or unparseable values (never invalid strings into typed columns).
    """
    if val is None:
        return None

    s_raw = str(val).strip()
    if s_raw.lower() in ("", "none", "null", "nan"):
        return None

    dt_lower = str(dt or "").strip().lower()

    if dt_lower in ("integer", "bigint", "int", "smallint"):
        try:
            return int(float(s_raw.replace(",", "")))
        except Exception:
            return None

    if dt_lower in ("double", "real", "float", "numeric", "decimal"):
        try:
            return float(s_raw.replace("$", "").replace(",", "").replace("%", ""))
        except Exception:
            return None

    if dt_lower == "date":
        try:
            # Handle formats like '2025-04-28', '2025-04-28 00:00:00', ISO '2025-04-28T00:00:00Z'
            s = s_raw
            if "T" in s:
                s = s.split("T")[0]
            elif " " in s:
                s = s.split(" ")[0]
            s = s.rstrip("Z").strip()
            return datetime.date.fromisoformat(s)
        except Exception:
            return None

    if dt_lower in ("datetime", "timestamp"):
        try:
            s = s_raw.rstrip("Z").strip()
            return datetime.datetime.fromisoformat(s)
        except Exception:
            return None

    if dt_lower in ("bool", "boolean"):
        s = s_raw.lower()
        if s in ("true", "1", "t", "yes", "y"):
            return True
        if s in ("false", "0", "f", "no", "n"):
            return False
        return None

    return s_raw


def format_contract_mismatch(
    actual_types: dict[str, Any],
    expected_types: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """
    Check actual column types in a Hyper extract against expected IR data types.
    Returns an error description string if a contract violation is found, or None if valid.
    """
    if not expected_types:
        return None

    for col_name, want_dtype in expected_types.items():
        if col_name not in actual_types:
            continue
        got_type_str = str(actual_types[col_name]).strip().upper()
        want_lower = str(want_dtype or "").strip().lower()

        if want_lower == "date" and got_type_str not in ("DATE", "TIMESTAMP"):
            return f"column '{col_name}' is {got_type_str}, expected DATE"
        if want_lower in ("datetime", "timestamp") and got_type_str not in ("TIMESTAMP", "DATE"):
            return f"column '{col_name}' is {got_type_str}, expected TIMESTAMP"
        if want_lower in ("integer", "bigint", "int") and got_type_str not in ("INT", "BIGINT", "SMALLINT"):
            return f"column '{col_name}' is {got_type_str}, expected INTEGER"
        if want_lower in ("double", "real", "float", "numeric", "decimal") and got_type_str not in ("DOUBLE", "FLOAT", "NUMERIC", "DECIMAL"):
            return f"column '{col_name}' is {got_type_str}, expected DOUBLE"

    return None
