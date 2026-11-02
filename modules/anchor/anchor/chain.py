"""The chain length advice: the user's formula, parsed (no eval)."""
import math, re





class ChainFormula:
    """The recommended-chain formula of the settings, e.g. "5*(D+B)" or "3 x D + 1 x LOA".

    Variables: D = deepest water in the next 24 h, B = bow height, LOA = length over all (any case). Numbers, + - * /,
    "x" or "×" for times, and brackets. Parsed into a small expression tree, never evaluated as code.
    """
    VARS = ("D", "B", "LOA")
    TOKEN = re.compile(r"\s*(?:(\d+(?:[.,]\d+)?)|(LOA|D|B)|([-+*/()x×]))", re.I)

    def __init__(self, text):
        self.text = str(text).strip(); self.toks = []; pos = 0
        while pos < len(self.text):
            m = self.TOKEN.match(self.text, pos)
            if not m or m.end() == pos:
                rest = self.text[pos:].strip()
                if not rest: break
                raise ValueError(f"Chain formula: cannot read '{rest[:12]}'. Use numbers, D, B, LOA, + - * / x and brackets")
            num_, var, op = m.groups(); pos = m.end()
            if num_: self.toks.append(("n", float(num_.replace(",", "."))))
            elif var: self.toks.append(("v", var.upper()))
            else: self.toks.append(("o", "*" if op in "x×X" else op))
        if not self.toks: raise ValueError("Chain formula is empty")
        self.i = 0; self.tree = self._expr()
        if self.i != len(self.toks): raise ValueError("Chain formula: unexpected text near the end")
        self(7.3, 1.3, 11.7)                                      # check it computes (values unlikely to divide by zero)

    def _peek(self): return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _expr(self):
        node = self._term()
        while self._peek() in (("o", "+"), ("o", "-")):
            op = self.toks[self.i][1]; self.i += 1; node = (op, node, self._term())
        return node

    def _term(self):
        node = self._factor()
        while self._peek() in (("o", "*"), ("o", "/")):
            op = self.toks[self.i][1]; self.i += 1; node = (op, node, self._factor())
        return node

    def _factor(self):
        kind, val = self._peek()
        if kind is None: raise ValueError("Chain formula ends too early")
        self.i += 1
        if kind == "n": return ("n", val)
        if kind == "v": return ("v", val)
        if val == "-": return ("neg", self._factor())
        if val == "(":
            node = self._expr()
            if self._peek() != ("o", ")"): raise ValueError("Chain formula: a bracket is not closed")
            self.i += 1; return node
        raise ValueError(f"Chain formula: unexpected '{val}'")

    def __call__(self, D, B, LOA):
        env = {"D": D, "B": B, "LOA": LOA}
        def ev(n):
            k = n[0]
            if k == "n": return n[1]
            if k == "v": return env[n[1]]
            if k == "neg": return -ev(n[1])
            a, b = ev(n[1]), ev(n[2])
            if k == "/" and b == 0: raise ValueError("Chain formula divides by zero")
            return a + b if k == "+" else a - b if k == "-" else a * b if k == "*" else a / b
        return ev(self.tree)


def chain_advice(formula, max_depth, bow_height, loa):
    """Recommended chain in whole metres (rounded up) from the settings' formula."""
    v = ChainFormula(formula)(max_depth, bow_height, loa)
    return max(0, math.ceil(v - 1e-9))
