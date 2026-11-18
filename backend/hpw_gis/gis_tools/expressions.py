"""Safe SQL-like WHERE clause evaluation for Select by Attributes / filters.

No eval(), no SQL engine: a tokenizer + recursive-descent parser builds boolean masks over a DataFrame.
SQL three-valued logic is honoured: comparisons against NULL are UNKNOWN and are never selected.

Grammar (case-insensitive keywords):
    expr     := or
    or       := and ( OR and )*
    and      := not ( AND not )*
    not      := NOT not | pred
    pred     := '(' expr ')' | operand ( cmp operand | [NOT] LIKE str | [NOT] IN '(' lits ')'
                 | IS [NOT] NULL | [NOT] BETWEEN operand AND operand )
    operand  := field | number | 'string' | DATE 'yyyy-mm-dd' | TRUE | FALSE
    field    := identifier | "quoted identifier"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

TOKEN_RE = re.compile(
    r"""\s*(?:
      (?P<num>-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)
    | (?P<str>'(?:[^']|'')*')
    | (?P<qid>"(?:[^"]|"")+")
    | (?P<op><>|!=|<=|>=|=|<|>)
    | (?P<lp>\() | (?P<rp>\)) | (?P<comma>,)
    | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.X,
)
KEYWORDS = {"AND", "OR", "NOT", "LIKE", "IN", "IS", "NULL", "BETWEEN", "TRUE", "FALSE", "DATE"}


class ExpressionError(ValueError):
    pass


@dataclass
class Tok:
    kind: str
    value: str


def tokenize(text: str) -> list[Tok]:
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"Unexpected character at position {pos}: {text[pos:pos + 15]!r}")
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "id" and val.upper() in KEYWORDS:
            kind, val = "kw", val.upper()
        out.append(Tok(kind, val))
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return out


# A tri-state value: (true_mask, unknown_mask)
TV = tuple[np.ndarray, np.ndarray]


class Parser:
    def __init__(self, df: pd.DataFrame, text: str):
        self.df = df
        self.toks = tokenize(text)
        self.i = 0
        self.fields_used: set[str] = set()
        self.colmap = {str(c).lower(): c for c in df.columns}

    def peek(self, kind: str | None = None, value: str | None = None) -> bool:
        if self.i >= len(self.toks):
            return False
        t = self.toks[self.i]
        return (kind is None or t.kind == kind) and (value is None or t.value == value)

    def take(self, kind: str | None = None, value: str | None = None) -> Tok:
        if not self.peek(kind, value):
            got = self.toks[self.i].value if self.i < len(self.toks) else "end of expression"
            raise ExpressionError(f"Expected {value or kind} but found {got!r}")
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self) -> np.ndarray:
        if not self.toks:
            raise ExpressionError("Expression is empty")
        t, _u = self.expr()
        if self.i != len(self.toks):
            raise ExpressionError(f"Unexpected token {self.toks[self.i].value!r}")
        return t

    def expr(self) -> TV:
        return self.or_()

    def or_(self) -> TV:
        t, u = self.and_()
        while self.peek("kw", "OR"):
            self.take()
            t2, u2 = self.and_()
            t, u = t | t2, (u | u2) & ~(t | t2)
        return t, u

    def and_(self) -> TV:
        t, u = self.not_()
        while self.peek("kw", "AND"):
            self.take()
            t2, u2 = self.not_()
            f1, f2 = ~t & ~u, ~t2 & ~u2
            t, u = t & t2, (u | u2) & ~(f1 | f2)
        return t, u

    def not_(self) -> TV:
        if self.peek("kw", "NOT"):
            self.take()
            t, u = self.not_()
            return ~t & ~u, u
        return self.pred()

    def operand(self) -> pd.Series:
        n = len(self.df)
        if self.peek("num"):
            v = float(self.take().value)
            return pd.Series([v] * n, index=self.df.index, dtype="float64")
        if self.peek("str"):
            return pd.Series([self._str(self.take().value)] * n, index=self.df.index, dtype=object)
        if self.peek("kw", "DATE"):
            self.take()
            s = self._str(self.take("str").value)
            try:
                ts = pd.Timestamp(s)
            except Exception as e:
                raise ExpressionError(f"Invalid DATE literal {s!r}") from e
            return pd.Series([ts] * n, index=self.df.index)
        if self.peek("kw", "TRUE") or self.peek("kw", "FALSE"):
            return pd.Series([self.take().value == "TRUE"] * n, index=self.df.index, dtype=object)
        if self.peek("id") or self.peek("qid"):
            return self.field()
        got = self.toks[self.i].value if self.i < len(self.toks) else "end"
        raise ExpressionError(f"Expected a field or value, found {got!r}")

    def field(self) -> pd.Series:
        t = self.take()
        name = t.value[1:-1].replace('""', '"') if t.kind == "qid" else t.value
        col = self.colmap.get(name.lower())
        if col is None:
            raise ExpressionError(f"Unknown field {name!r}. Available: {', '.join(map(str, self.df.columns))}")
        self.fields_used.add(str(col))
        return self.df[col]

    @staticmethod
    def _str(raw: str) -> str:
        return raw[1:-1].replace("''", "'")

    def pred(self) -> TV:
        if self.peek("lp"):
            self.take()
            r = self.expr()
            self.take("rp")
            return r
        left = self.operand()
        neg = False
        if self.peek("kw", "IS"):
            self.take()
            if self.peek("kw", "NOT"):
                self.take()
                neg = True
            self.take("kw", "NULL")
            isnull = left.isna().to_numpy()
            return (~isnull if neg else isnull), np.zeros(len(left), bool)
        if self.peek("kw", "NOT"):
            self.take()
            neg = True
        if self.peek("kw", "LIKE"):
            self.take()
            pat = self._str(self.take("str").value)
            rx = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pat) + "$"
            null = left.isna().to_numpy()
            m = left.astype(str).str.match(rx, case=True).to_numpy() & ~null
            return self._tv(m, null, neg)
        if self.peek("kw", "IN"):
            self.take()
            self.take("lp")
            vals = [self._literal()]
            while self.peek("comma"):
                self.take()
                vals.append(self._literal())
            self.take("rp")
            null = left.isna().to_numpy()
            m = self._isin(left, vals) & ~null
            return self._tv(m, null, neg)
        if self.peek("kw", "BETWEEN"):
            self.take()
            lo = self.operand()
            self.take("kw", "AND")
            hi = self.operand()
            null = (left.isna() | lo.isna() | hi.isna()).to_numpy()
            m = (self._cmp(left, ">=", lo) & self._cmp(left, "<=", hi)) & ~null
            return self._tv(m, null, neg)
        if neg:
            raise ExpressionError("NOT must be followed by LIKE, IN or BETWEEN here")
        op = self.take("op").value
        right = self.operand()
        null = (left.isna() | right.isna()).to_numpy()
        return self._cmp(left, op, right) & ~null, null

    @staticmethod
    def _tv(m: np.ndarray, null: np.ndarray, neg: bool) -> TV:
        return ((~m & ~null) if neg else m), null

    def _literal(self):
        if self.peek("num"):
            return float(self.take().value)
        if self.peek("str"):
            return self._str(self.take().value)
        raise ExpressionError("IN list may only contain numbers or 'strings'")

    @staticmethod
    def _isin(s: pd.Series, vals: list) -> np.ndarray:
        if pd.api.types.is_numeric_dtype(s):
            nums = [v for v in vals if isinstance(v, float)]
            return s.isin(nums).to_numpy()
        return s.astype(str).isin([str(v) if not isinstance(v, float) else (str(int(v)) if v.is_integer() else str(v))
                                   for v in vals]).to_numpy()

    @staticmethod
    def _cmp(a: pd.Series, op: str, b: pd.Series) -> np.ndarray:
        an, bn = pd.api.types.is_numeric_dtype(a), pd.api.types.is_numeric_dtype(b)
        if an != bn and not (pd.api.types.is_bool_dtype(a) or pd.api.types.is_bool_dtype(b)):
            # mixed numeric/string comparison: coerce strings to numbers (non-numeric -> unknown/false)
            a = pd.to_numeric(a, errors="coerce") if not an else a
            b = pd.to_numeric(b, errors="coerce") if not bn else b
        try:
            if op == "=":
                r = a == b
            elif op in ("<>", "!="):
                r = a != b
            elif op == "<":
                r = a < b
            elif op == "<=":
                r = a <= b
            elif op == ">":
                r = a > b
            else:
                r = a >= b
        except TypeError as e:
            raise ExpressionError(f"Cannot compare these values with {op}: {e}") from e
        return r.fillna(False).to_numpy(dtype=bool)


def evaluate(df: pd.DataFrame, where: str) -> tuple[np.ndarray, set[str]]:
    p = Parser(df, where)
    mask = p.parse()
    return mask, p.fields_used
