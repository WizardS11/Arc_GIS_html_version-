import numpy as np
import pandas as pd
import pytest

from hpw_gis.gis_tools.expressions import ExpressionError, evaluate

DF = pd.DataFrame({
    "UFID": ["P1", "P2", "P3", "P4", "P5"],
    "DIAMETER_IN": [8, 12, None, 24, 15],
    "MATERIAL": ["PVC", "VCP", "PVC", None, "O'Brien"],
    "INSTALL_YR": pd.array([1998, None, 2004, 1975, 1962], dtype="Int64"),
})


def sel(where):
    m, _ = evaluate(DF, where)
    return list(DF.loc[m, "UFID"])


@pytest.mark.parametrize("where,expected", [
    ("DIAMETER_IN >= 12", ["P2", "P4", "P5"]),
    ("diameter_in > 8 AND material = 'VCP'", ["P2"]),
    ("MATERIAL IN ('PVC', 'VCP')", ["P1", "P2", "P3"]),
    ("MATERIAL NOT IN ('PVC')", ["P2", "P5"]),           # NULL is never selected
    ("MATERIAL LIKE 'P%'", ["P1", "P3"]),
    ("MATERIAL NOT LIKE 'P%'", ["P2", "P5"]),
    ("DIAMETER_IN BETWEEN 10 AND 20", ["P2", "P5"]),
    ("DIAMETER_IN IS NULL", ["P3"]),
    ("MATERIAL IS NOT NULL AND INSTALL_YR IS NULL", ["P2"]),
    ("NOT (DIAMETER_IN > 10)", ["P1"]),                  # unknown stays unknown under NOT
    ("DIAMETER_IN > 100 OR MATERIAL = 'PVC'", ["P1", "P3"]),
    ("MATERIAL = 'O''Brien'", ["P5"]),
    ('"UFID" = \'P4\'', ["P4"]),
    ("INSTALL_YR < 1980", ["P4", "P5"]),
])
def test_where_clauses(where, expected):
    assert sel(where) == expected


@pytest.mark.parametrize("bad", [
    "", "DIAMETER_IN >", "NOPE = 1", "UFID = 'x'; DROP TABLE layers", "__import__('os')", "1 = 1 )",
    "MATERIAL LIKE PVC",
])
def test_rejects_invalid(bad):
    with pytest.raises(ExpressionError):
        evaluate(DF, bad)


def test_three_valued_logic_complement():
    """A predicate and its NOT never overlap, and NULL rows are in neither."""
    a, _ = evaluate(DF, "DIAMETER_IN > 10")
    b, _ = evaluate(DF, "NOT DIAMETER_IN > 10")
    assert not np.any(a & b)
    assert list(DF.loc[~(a | b), "UFID"]) == ["P3"]
