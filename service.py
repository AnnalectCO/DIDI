"""Capa única de servicio: config (dict) -> resultados + alertas.
La usan por igual la interfaz Streamlit y las herramientas del asistente, para que ambas den las mismas cifras."""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd
from engine import Group, optimize, evaluate, InfeasibleError

DEFAULT_ALERTS = {
    "near_bound_pct": 0.10,        # ámbar si el gasto queda a <10% del rango de un límite
    "mroi_dispersion_eps": 0.02,   # dispersión de MROI entre canales interiores (parámetro de la mesa)
    "unit_change_alert": 0.20,     # cambio de gasto por unidad que exige revisión (parámetro de la mesa)
    "c_gap_alert": 0.05,           # diferencia de c promedio entre unidades
    "modeled_range_pct": 0.60,     # PDF › Limitaciones y Fase 2 › Extrapolación (±60%)
    "breakeven_mroi": None,        # lo define el usuario; sin valor no se evalúa
    "curves_date": None,           # fecha de reentrenamiento (YYYY-MM-DD) para alerta de 90 días
}


def default_cfg():
    return {"total": None, "limit_pct": 0.60, "channel_min": {}, "channel_max": {}, "fixed": {},
            "unit_min": {}, "unit_max": {}, "medio_min": {}, "medio_max": {}, "mode": "free",
            "factor": {}, "manual": {}, "alerts": {}}


def _bounds(df, cfg):
    p = cfg["limit_pct"]; x0 = df.x0.values
    lo = x0 * (1 - p); hi = x0 * (1 + p)
    ids = list(df.id)
    for k, v in cfg["channel_min"].items(): lo[ids.index(k)] = v
    for k, v in cfg["channel_max"].items(): hi[ids.index(k)] = v
    for k, v in cfg["fixed"].items(): lo[ids.index(k)] = v; hi[ids.index(k)] = v
    return lo, hi


def _groups(df, cfg):
    g = []
    for u in df.bu.unique():
        lo, hi = cfg["unit_min"].get(u), cfg["unit_max"].get(u)
        if lo is not None or hi is not None:
            g.append(Group(f"Unidad {u}", np.where(df.bu.values == u)[0], lo, hi, "unidad"))
    for m in df.ch.unique():
        lo, hi = cfg["medio_min"].get(m), cfg["medio_max"].get(m)
        if lo is not None or hi is not None:
            g.append(Group(f"Medio {m}", np.where(df.ch.values == m)[0], lo, hi, "medio"))
    return g


def unit_summary(t):
    s = t.groupby("bu").agg(gasto_base=("x0", "sum"), gasto=("x", "sum"), valor_base=("rev0", "sum"), valor=("rev", "sum"))
    s.loc["Total"] = s.sum()
    s["cambio_gasto"] = s.gasto - s.gasto_base; s["cambio_gasto_pct"] = s.gasto / s.gasto_base - 1
    s["cambio_valor"] = s.valor - s.valor_base
    return s


def medio_summary(t):
    s = t.groupby("ch").agg(gasto_base=("x0", "sum"), gasto=("x", "sum"), valor=("rev", "sum"))
    s["pct_mix"] = s.gasto / s.gasto.sum(); s["cambio_pct"] = s.gasto / s.gasto_base - 1
    return s


def run(df, cfg_in):
    cfg = default_cfg(); cfg.update({k: v for k, v in cfg_in.items()}); cfg["alerts"] = {**DEFAULT_ALERTS, **cfg_in.get("alerts", {})}
    total = float(cfg["total"] if cfg["total"] else df.x0.sum())
    lo, hi = _bounds(df, cfg); groups = _groups(df, cfg); anchored = cfg["mode"] == "anchored"
    if anchored and abs(total - df.x0.sum()) > 1:
        raise InfeasibleError(f"En modo 'unidad anclada' cada unidad conserva su gasto base, así que el presupuesto total debe ser {df.x0.sum()/1e6:,.2f} M (hoy: {total/1e6:,.2f} M). Usa 'bolsa libre' para cambiar el total.")
    factor = cfg["factor"]
    base = evaluate(df, df.x0.values, factor, lo, hi)
    x, info = optimize(df, total, lo, hi, factor, groups, anchored)
    opt = evaluate(df, x, factor, lo, hi)
    res = {"cfg": cfg, "total": total, "lo": lo, "hi": hi, "groups": groups, "base": base, "opt": opt, "info": info,
           "unit_opt": unit_summary(opt), "medio_opt": medio_summary(opt)}
    if cfg["manual"]:
        xm = df.x0.values.copy()
        for k, v in cfg["manual"].items(): xm[list(df.id).index(k)] = v
        man = evaluate(df, xm, factor, lo, hi); res["manual"] = man
        res["unit_manual"] = unit_summary(man); res["medio_manual"] = medio_summary(man)
    res["alerts"] = alerts(df, res)
    return res


def _group_sums(df, t, groups):
    return [(g, float(t.x.values[g.idx].sum())) for g in groups]


def alerts(df, res):
    A = res["cfg"]["alerts"]; out = []; add = lambda lv, msg: out.append({"nivel": lv, "alerta": msg})
    total = res["total"]
    for name, t in (("Óptimo", res["opt"]), ("Propuesta manual", res.get("manual"))):
        if t is None: continue
        gap = t.x.sum() - total
        if abs(gap) > 1: add("rojo", f"{name}: la suma de canales difiere del presupuesto en {gap/1e6:+,.2f} M MXN.")
        rng = (t.hi - t.lo).clip(lower=1)
        for _, r in t.iterrows():
            if r.x < r.lo - 1 or r.x > r.hi + 1:
                add("rojo", f"{name}: {r.label} ({r.id}) fuera de su rango [{r.lo/1e6:,.1f}, {r.hi/1e6:,.1f}] M.")
            elif name == "Propuesta manual" and r.estado != "FIJO" and (min(r.x - r.lo, r.hi - r.x) / rng[_] < A["near_bound_pct"]):
                add("ámbar", f"{name}: {r.label} a menos de {A['near_bound_pct']:.0%} del rango de un límite.")
        for g, s in _group_sums(df, t, res["groups"]):
            if g.lo is not None and s < g.lo - 1: add("rojo", f"{name}: {g.name} ({s/1e6:,.1f} M) por debajo de su mínimo {g.lo/1e6:,.1f} M.")
            elif g.hi is not None and s > g.hi + 1: add("rojo", f"{name}: {g.name} ({s/1e6:,.1f} M) por encima de su máximo {g.hi/1e6:,.1f} M.")
            elif name == "Óptimo" and ((g.lo is not None and abs(s - g.lo) < 1e3) or (g.hi is not None and abs(s - g.hi) < 1e3)):
                add("ámbar", f"Óptimo: el límite de {g.name} está activo; condiciona el resultado.")
    opt = res["opt"]
    nb = opt[opt.estado.isin(["MIN", "MAX"])]
    for _, r in nb.iterrows(): add("ámbar", f"Óptimo: {r.label} ({r.id}) en {r.estado}; su MROI ({r.mroi:.3f}) no tiene que igualar a los demás.")
    if len(nb) / len(opt) >= 0.5: add("ámbar", f"Óptimo: {len(nb)} de {len(opt)} canales en límite; el resultado depende más de los rangos que de las curvas.")
    if "manual" in res:
        man = res["manual"]; inter = man[man.estado == "Interior"].mroi
        if len(inter) > 1 and inter.max() - inter.min() > A["mroi_dispersion_eps"]:
            gain = opt.rev.sum() - man.rev.sum()
            add("ámbar", f"Propuesta manual no es óptima: MROI entre {inter.min():.3f} y {inter.max():.3f}. Reoptimizar sumaría {gain/1e6:,.2f} M de valor.")
    for u, row in res["unit_opt"].drop("Total").iterrows():
        if abs(row.cambio_gasto_pct) > A["unit_change_alert"]:
            add("ámbar", f"Cambio material en {u}: {row.cambio_gasto_pct:+.1%} ({row.cambio_gasto/1e6:+,.1f} M) frente al plan. Validar con sus responsables (umbral {A['unit_change_alert']:.0%}, definido por la mesa).")
    for _, r in opt.iterrows():
        if abs(r.x / r.x0 - 1) > A["modeled_range_pct"] + 1e-6:
            add("rojo", f"Extrapolación: {r.label} se aleja {r.x/r.x0-1:+.0%} del gasto base; fuera del rango modelado (±{A['modeled_range_pct']:.0%}, PDF › Limitaciones).")
    be = A.get("breakeven_mroi")
    if be is not None:
        low = opt[opt.mroi < be]
        for _, r in low.iterrows(): add("ámbar", f"MROI de {r.label} ({r.mroi:.3f}) por debajo del umbral de equilibrio definido ({be}).")
        lam = np.nanmean(list(res["info"]["lambda"].values()))
        if lam < be: add("ámbar", f"El valor marginal de la bolsa (λ={lam:.3f}) está bajo el umbral {be}: gastar más ya no devuelve ese valor.")
    cm = df.groupby("bu").c.mean()
    if len(cm) == 2 and abs(cm.iloc[0] - cm.iloc[1]) > A["c_gap_alert"]:
        add("ámbar", f"Comparabilidad: exponente c medio {cm.index[0]} {cm.iloc[0]:.3f} vs {cm.index[1]} {cm.iloc[1]:.3f}; la diferencia puede venir de la especificación, no del mercado (PDF › Limitaciones). Ver Sensibilidad.")
    for u, g in df.groupby("bu"):
        rep = g.c.round(4).value_counts(); rep = rep[rep >= 3]
        for cval, k in rep.items(): add("info", f"{u}: {k} canales comparten c={cval}; sus curvas casi no se distinguen entre sí.")
    if A.get("curves_date"):
        age = (dt.date.today() - dt.date.fromisoformat(str(A["curves_date"]))).days
        if age > 90: add("ámbar", f"Curvas con {age} días sin reentrenar (revisión trimestral, PDF › Plan de Trabajo).")
    if all(v == 1 for v in res["cfg"]["factor"].values()) or not res["cfg"]["factor"]:
        add("info", "Valor = revenue incremental, no margen. Cargar márgenes por unidad en 'factor de valor' para optimizar rentabilidad.")
    order = {"rojo": 0, "ámbar": 1, "info": 2}
    return sorted(out, key=lambda a: order[a["nivel"]])
