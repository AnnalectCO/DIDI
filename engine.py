"""Motor determinista de asignación de presupuesto sobre curvas ABC.

Revenue_i(x) = f_u * a / (1 + (x/b)^c),  c < 0   (f_u = factor de valor de la unidad; 1 = revenue puro)
Problema: max sum_i Revenue_i(x_i)  s.a.  sum x_i = B,  lo_i <= x_i <= hi_i,  límites por grupo (unidad / medio).
Con -1 < c < 0 cada curva es cóncava -> problema convexo -> óptimo único.

Rutas de solución
- Exacta (bisección sobre λ = MROI de equilibrio): sin límites de grupo, o con límites solo por unidad de negocio.
- SLSQP con gradiente analítico: cuando hay límites por medio (grupos que cruzan unidades).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize, linprog

EPS = 1.0  # MXN, piso numérico para evitar x = 0


class InfeasibleError(ValueError):
    pass


@dataclass
class Group:
    name: str
    idx: np.ndarray
    lo: float | None = None
    hi: float | None = None
    kind: str = "medio"  # "unidad" | "medio"


# ----------------------------------------------------------------- datos
_COLS = {
    "Category": "bu", "Curve name": "ch", "Curve Detail": "det",
    "Annual Spend of the Curve": "x0", "A": "a", "C": "c", "ICP B": "b",
    "Annual Incremental KPI Due to @ Historic Spend": "inc_rep",
}


def load_curves(path_or_file) -> pd.DataFrame:
    name = str(getattr(path_or_file, "name", path_or_file)).lower()
    raw = pd.read_csv(path_or_file) if name.endswith(".csv") else pd.read_excel(path_or_file)
    if "bu" in raw.columns:
        d = raw.copy()
    else:
        missing = [c for c in _COLS if c not in raw.columns]
        if missing:
            raise ValueError(f"Faltan columnas en el archivo de curvas: {missing}")
        d = raw[list(_COLS)].rename(columns=_COLS)
    d = d.reset_index(drop=True)
    if "id" not in d.columns:
        d.insert(0, "id", [f"C{i + 1:02d}" for i in range(len(d))])
    if not ((d.c < 0).all() and (d.a > 0).all() and (d.b > 0).all() and (d.x0 > 0).all()):
        raise ValueError("Parámetros inválidos: se requiere a>0, b>0, c<0 y gasto base>0.")
    d["label"] = d.bu.str.replace("Food Delivery", "Food").str.replace("RideShare", "Ride") + " · " + d.ch + " – " + d.det
    if (d.c < -1).any():
        d.attrs["warning"] = "Hay curvas con c < -1 (forma de S): el problema deja de ser convexo; el óptimo puede no ser único."
    return d


# ----------------------------------------------------------------- curvas
def revenue(x, a, b, c):
    x = np.maximum(x, 1e-9)
    return a / (1.0 + (x / b) ** c)


def mroi(x, a, b, c):
    x = np.maximum(x, 1e-9)
    u = (x / b) ** c
    return -a * c * u / (x * (1.0 + u) ** 2)


# ----------------------------------------------------------------- solución exacta
def _solve_lambda(ae, b, c, lo, hi, B):
    """Reparte B entre las curvas dadas igualando MROI (λ) con límites individuales."""
    n = len(ae)
    if lo.sum() - 1e-6 > B or hi.sum() + 1e-6 < B:
        raise InfeasibleError(f"Presupuesto {B/1e6:,.1f} M fuera de [{lo.sum()/1e6:,.1f}, {hi.sum()/1e6:,.1f}] M permitido por los límites.")

    def xs(lam):
        out = np.empty(n)
        for k in range(n):
            m = lambda x: mroi(x, ae[k], b[k], c[k]) - lam
            if m(lo[k]) <= 0:
                out[k] = lo[k]
            elif m(hi[k]) >= 0:
                out[k] = hi[k]
            else:
                out[k] = brentq(m, lo[k], hi[k], xtol=1e-7, rtol=1e-14)
        return out

    l1, l2 = 1e-9, 1e4
    for _ in range(120):
        lm = np.sqrt(l1 * l2)
        if xs(lm).sum() > B:
            l1 = lm
        else:
            l2 = lm
    x = xs(lm)
    gap = B - x.sum()
    if abs(gap) > 1e-3:  # reparte residuo numérico entre canales interiores
        free = (x > lo + 1) & (x < hi - 1)
        if free.any():
            x[free] += gap / free.sum()
    return x, lm


def _unit_idx(df):
    return {u: np.where(df.bu.values == u)[0] for u in df.bu.unique()}


def optimize(df, total, lo, hi, factor=None, groups=(), anchored=False):
    """Devuelve (x, info). `factor`: dict unidad->factor. `groups`: lista de Group."""
    a = df.a.values.astype(float); b = df.b.values.astype(float); c = df.c.values.astype(float)
    f = np.array([(factor or {}).get(u, 1.0) for u in df.bu.values], dtype=float)
    ae = a * f
    lo = np.maximum(np.asarray(lo, float), EPS); hi = np.asarray(hi, float)
    if (lo > hi + 1e-6).any():
        bad = df.id.values[lo > hi + 1e-6]
        raise InfeasibleError(f"Mínimo mayor que máximo en: {', '.join(bad)}")
    units = _unit_idx(df)
    groups = list(groups)
    if anchored:
        groups = [g for g in groups if g.kind != "unidad"]
        for u, ix in units.items():
            B_u = float(df.x0.values[ix].sum())
            groups.append(Group(f"Unidad {u}", ix, B_u, B_u, "unidad"))
    unit_only = all(g.kind == "unidad" for g in groups) and len(units) == 2
    if unit_only:
        return _optimize_units(ae, b, c, lo, hi, total, groups, units, df)
    return _optimize_slsqp(ae, b, c, lo, hi, total, groups, df)


def _optimize_units(ae, b, c, lo, hi, B, groups, units, df):
    (u1, i1), (u2, i2) = list(units.items())
    lim = {u: [None, None] for u in units}
    for g in groups:
        u = df.bu.values[g.idx[0]]
        lim[u] = [g.lo, g.hi]
    L = {}; H = {}
    for u, ix in units.items():
        L[u] = max(lim[u][0] or 0.0, lo[ix].sum()); H[u] = min(lim[u][1] if lim[u][1] is not None else np.inf, hi[ix].sum())
        if L[u] > H[u] + 1e-6:
            raise InfeasibleError(f"{u}: el mínimo de la unidad ({L[u]/1e6:,.1f} M) excede su máximo posible ({H[u]/1e6:,.1f} M).")
    b1_lo, b1_hi = max(L[u1], B - H[u2]), min(H[u1], B - L[u2])
    if b1_lo > b1_hi + 1e-6:
        raise InfeasibleError("Los límites por unidad no permiten sumar el presupuesto total indicado.")
    x_free, lam = _solve_lambda(ae, b, c, lo, hi, B)
    b1 = x_free[i1].sum()
    x = np.empty(len(ae)); lam_u = {}
    if b1 < b1_lo - 1e-3 or b1 > b1_hi + 1e-3:
        b1c = min(max(b1, b1_lo), b1_hi)
        x[i1], lam_u[u1] = _solve_lambda(ae[i1], b[i1], c[i1], lo[i1], hi[i1], b1c)
        x[i2], lam_u[u2] = _solve_lambda(ae[i2], b[i2], c[i2], lo[i2], hi[i2], B - b1c)
        method = "exacta (límite de unidad activo)"
    else:
        x = x_free; lam_u = {u1: lam, u2: lam}; method = "exacta"
    return x, {"lambda": lam_u, "method": method}


def _feasible(n, total, lo, hi, groups):
    A_eq = [np.ones(n)]; b_eq = [total]; A_ub = []; b_ub = []
    for g in groups:
        row = np.zeros(n); row[g.idx] = 1
        if g.lo is not None and g.hi is not None and abs(g.hi - g.lo) < 1e-6:
            A_eq.append(row); b_eq.append(g.lo); continue
        if g.lo is not None: A_ub.append(-row); b_ub.append(-g.lo)
        if g.hi is not None: A_ub.append(row); b_ub.append(g.hi)
    r = linprog(np.zeros(n), A_ub=np.array(A_ub) if A_ub else None, b_ub=b_ub or None,
                A_eq=np.array(A_eq), b_eq=b_eq, bounds=list(zip(lo, hi)), method="highs")
    return r.status == 0, r


def _optimize_slsqp(ae, b, c, lo, hi, B, groups, df):
    n = len(ae); sc = 1e6
    ok, r0 = _feasible(n, B, lo, hi, groups)
    if not ok:
        raise InfeasibleError("Las restricciones (mínimos/máximos por canal, unidad o medio y presupuesto total) son incompatibles entre sí.")
    z0 = r0.x / sc
    try:  # mejor punto de partida: solución sin límites de grupo, si ya cumple
        xf, _ = _solve_lambda(ae, b, c, lo, hi, B)
        okg = all((g.lo is None or xf[g.idx].sum() >= g.lo - 1) and (g.hi is None or xf[g.idx].sum() <= g.hi + 1) for g in groups)
        if okg:
            return xf, {"lambda": {"global": _lam_from(xf, ae, b, c, lo, hi)}, "method": "exacta (límites de grupo inactivos)"}
    except InfeasibleError:
        pass
    f = lambda z: -revenue(z * sc, ae, b, c).sum() / sc
    g_ = lambda z: -mroi(z * sc, ae, b, c)
    cons = [{"type": "eq", "fun": lambda z: z.sum() - B / sc, "jac": lambda z: np.ones(n)}]
    for g in groups:
        row = np.zeros(n); row[g.idx] = 1
        if g.lo is not None and g.hi is not None and abs(g.hi - g.lo) < 1e-6:
            cons.append({"type": "eq", "fun": (lambda z, row=row, v=g.lo: row @ z - v / sc), "jac": (lambda z, row=row: row)})
            continue
        if g.lo is not None:
            cons.append({"type": "ineq", "fun": (lambda z, row=row, v=g.lo: row @ z - v / sc), "jac": (lambda z, row=row: row)})
        if g.hi is not None:
            cons.append({"type": "ineq", "fun": (lambda z, row=row, v=g.hi: v / sc - row @ z), "jac": (lambda z, row=row: -row)})
    res = minimize(f, z0, jac=g_, bounds=list(zip(lo / sc, hi / sc)), constraints=cons, method="SLSQP",
                   options={"ftol": 1e-15, "maxiter": 1000})
    x = res.x * sc
    viol = abs(x.sum() - B)
    for g in groups:
        s = x[g.idx].sum()
        if g.lo is not None: viol = max(viol, g.lo - s)
        if g.hi is not None: viol = max(viol, s - g.hi)
    if viol > 50:  # MXN
        raise RuntimeError(f"El optimizador no convergió a una solución factible (violación {viol:,.0f} MXN).")
    return x, {"lambda": {"global": _lam_from(x, ae, b, c, lo, hi)}, "method": "SLSQP (límites por medio activos)"}


def _lam_from(x, ae, b, c, lo, hi):
    m = mroi(x, ae, b, c); interior = (x > lo + 1) & (x < hi - 1)
    return float(np.median(m[interior])) if interior.any() else float("nan")


# ----------------------------------------------------------------- evaluación
def evaluate(df, x, factor=None, lo=None, hi=None):
    f = np.array([(factor or {}).get(u, 1.0) for u in df.bu.values])
    a, b, c = df.a.values, df.b.values, df.c.values
    x = np.asarray(x, float)
    out = df[["id", "bu", "ch", "det", "label", "x0"]].copy()
    out["x"] = x
    out["cambio_pct"] = x / df.x0.values - 1
    out["rev0"] = revenue(df.x0.values, a * f, b, c)
    out["rev"] = revenue(x, a * f, b, c)
    out["roi"] = out.rev / np.maximum(x, 1)
    out["mroi"] = mroi(x, a * f, b, c)
    out["mroi0"] = mroi(df.x0.values, a * f, b, c)
    if lo is not None:
        st = np.where(np.abs(np.asarray(hi) - np.asarray(lo)) < 1, "FIJO",
             np.where(x <= np.asarray(lo) * (1 + 1e-6) + 1, "MIN", np.where(x >= np.asarray(hi) * (1 - 1e-6) - 1, "MAX", "Interior")))
        out["lo"] = lo; out["hi"] = hi; out["estado"] = st
    return out


def sensitivity_c(df, total, lo, hi, factor=None, groups=(), anchored=False, deltas=(-0.10, -0.05, 0.0, 0.05, 0.10)):
    """Mueve c de cada unidad y recalibra b para conservar el revenue base de cada curva (a fijo)."""
    a, b, c, x0 = df.a.values, df.b.values, df.c.values, df.x0.values
    R0 = revenue(x0, a, b, c)
    units = df.bu.values; us = list(dict.fromkeys(units))
    rows = []
    base_rev = None
    for d1 in deltas:
        for d2 in deltas:
            cs = c.copy(); cs[units == us[0]] += d1; cs[units == us[1]] += d2
            if (cs >= 0).any():
                continue
            bn = x0 / ((a / R0 - 1) ** (1 / cs))
            d2f = df.copy(); d2f["c"] = cs; d2f["b"] = bn
            try:
                x, info = optimize(d2f, total, lo, hi, factor, groups, anchored)
            except (InfeasibleError, RuntimeError):
                continue
            f = np.array([(factor or {}).get(u, 1.0) for u in units])
            rv = revenue(x, a * f, bn, cs).sum(); r0 = R0.dot(f)
            rec = {f"Δc {us[0]}": d1, f"Δc {us[1]}": d2, "valor_total": rv, "uplift_vs_plan": rv / r0 - 1}
            for u in us: rec[f"gasto_{u}"] = x[units == u].sum()
            rows.append(rec)
    return pd.DataFrame(rows)


def frontier(df, total, lo, hi, factor=None, groups=(), shares=None):
    """Mejor valor posible según qué % de la bolsa va a la primera unidad (óptimo dentro de cada unidad)."""
    us = list(dict.fromkeys(df.bu.values)); u1 = us[0]
    base_share = df.x0.values[df.bu.values == u1].sum() / df.x0.sum()
    shares = sorted(set(list(np.arange(0.20, 0.76, 0.05).round(2)) + [round(base_share, 4)])) if shares is None else shares
    rows = []
    for s in shares:
        ix1 = np.where(df.bu.values == u1)[0]; ix2 = np.where(df.bu.values != u1)[0]
        g = [x for x in groups if x.kind != "unidad"] + [Group(u1, ix1, total * s, total * s, "unidad"), Group(us[1], ix2, total * (1 - s), total * (1 - s), "unidad")]
        try:
            x, _ = optimize(df, total, lo, hi, factor, g, False)
        except (InfeasibleError, RuntimeError):
            continue
        f = np.array([(factor or {}).get(u, 1.0) for u in df.bu.values])
        rows.append({"pct_" + u1: s, "gasto_" + u1: total * s, "valor_total": revenue(x, df.a.values * f, df.b.values, df.c.values).sum()})
    return pd.DataFrame(rows)
