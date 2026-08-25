"""
Unit tests for Hyper SQL type mapping, dimension value coercion, and contract verification.
Validates the fix for Tableau Error Code 6EA18A9E (TEXT-typed date column vs Month derivation).
"""

import datetime
import pytest
from app.utils.sql_types import sql_type_for, coerce_dim_value, format_contract_mismatch
from tableauhyperapi import SqlType


def test_sql_type_mapping():
    """Verify data type mapping matrix to Tableau Hyper SqlTypes."""
    # Integer types
    assert sql_type_for("integer") == SqlType.int()
    assert sql_type_for("int") == SqlType.int()
    assert sql_type_for("bigint") == SqlType.big_int()
    assert sql_type_for("smallint") == SqlType.int()

    # Floating / Numeric types
    assert sql_type_for("double") == SqlType.double()
    assert sql_type_for("real") == SqlType.double()
    assert sql_type_for("float") == SqlType.double()
    assert sql_type_for("numeric") == SqlType.double()
    assert sql_type_for("decimal") == SqlType.double()

    # Date and Time types
    assert sql_type_for("date") == SqlType.date()
    assert sql_type_for("datetime") == SqlType.timestamp()
    assert sql_type_for("timestamp") == SqlType.timestamp()
    assert sql_type_for("time") == SqlType.time()

    # Boolean types
    assert sql_type_for("bool") == SqlType.bool()
    assert sql_type_for("boolean") == SqlType.bool()

    # Strings and unknown types default to TEXT
    assert sql_type_for("string") == SqlType.text()
    assert sql_type_for("utf8char") == SqlType.text()
    assert sql_type_for("varchar") == SqlType.text()
    assert sql_type_for(None) == SqlType.text()
    assert sql_type_for("unknown_custom_type") == SqlType.text()


def test_coerce_dim_value_dates():
    """Verify coercion of date strings to datetime.date objects."""
    # Standard ISO date
    d1 = coerce_dim_value("date", "2025-04-28")
    assert isinstance(d1, datetime.date)
    assert d1 == datetime.date(2025, 4, 28)

    # Date with trailing time (space separated)
    d2 = coerce_dim_value("date", "2025-11-15 00:00:00")
    assert isinstance(d2, datetime.date)
    assert d2 == datetime.date(2025, 11, 15)

    # ISO-T format with Z
    d3 = coerce_dim_value("date", "2023-04-02T14:30:00Z")
    assert isinstance(d3, datetime.date)
    assert d3 == datetime.date(2023, 4, 2)

    # Datetime / timestamp
    dt1 = coerce_dim_value("datetime", "2025-04-28T12:00:00")
    assert isinstance(dt1, datetime.datetime)
    assert dt1 == datetime.datetime(2025, 4, 28, 12, 0, 0)

    # Null / Empty / NaN / invalid
    assert coerce_dim_value("date", None) is None
    assert coerce_dim_value("date", "") is None
    assert coerce_dim_value("date", "None") is None
    assert coerce_dim_value("date", "null") is None
    assert coerce_dim_value("date", "nan") is None
    assert coerce_dim_value("date", "not-a-date") is None


def test_coerce_dim_value_numeric_and_text():
    """Verify coercion of numeric and text dimensions."""
    # Integer
    assert coerce_dim_value("integer", "46") == 46
    assert coerce_dim_value("int", " 100 ") == 100
    assert coerce_dim_value("int", "100.0") == 100
    assert coerce_dim_value("integer", "invalid") is None

    # Double
    assert coerce_dim_value("double", "$1,234.56") == 1234.56
    assert coerce_dim_value("numeric", "50.5%") == 50.5
    assert coerce_dim_value("double", "invalid") is None

    # Boolean
    assert coerce_dim_value("bool", "true") is True
    assert coerce_dim_value("bool", "1") is True
    assert coerce_dim_value("boolean", "false") is False
    assert coerce_dim_value("boolean", "0") is False

    # Text / String
    assert coerce_dim_value("string", "Loss Cause A") == "Loss Cause A"
    assert coerce_dim_value("utf8char", "OH") == "OH"


def test_format_contract_mismatch():
    """Verify contract mismatch detection."""
    actual = {
        "Loss Cause": "TEXT",
        "Loss Date": "TEXT",
        "Fraud Score": "INT",
        "Total Incurred USD": "DOUBLE",
    }

    # Expected Loss Date to be date, but got TEXT -> mismatch detected!
    expected = {
        "Loss Cause": "string",
        "Loss Date": "date",
        "Fraud Score": "integer",
    }
    mismatch = format_contract_mismatch(actual, expected)
    assert mismatch is not None
    assert "column 'Loss Date' is TEXT, expected DATE" in mismatch

    # When Loss Date is DATE -> no mismatch
    actual_valid = {
        "Loss Cause": "TEXT",
        "Loss Date": "DATE",
        "Fraud Score": "INT",
        "Total Incurred USD": "DOUBLE",
    }
    assert format_contract_mismatch(actual_valid, expected) is None
