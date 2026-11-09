"""Herramientas (function calling) para que un LLM use el MISMO motor que la interfaz.
Los esquemas son compatibles con APIs tipo OpenAI. Todas las cifras salen del motor, nunca del modelo."""
from __future__ import annotations
import json
import numpy as np
from engine import sensitivity_c, frontier
import service

M = 1e6
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "run_scenario",
        "description": "Calcula el reparto óptimo del presupuesto entre unidades y canales y devuelve cifras, límites activos, MROI y alertas. Usa montos en millones de MXN.",
        "parameters": {"type": "object", "properties": {
            "total_m": {"type": "number", "description": "Presupuesto total en M MXN. Omitir = presupuesto base."},
            "limit_pct": {"type": "number", "description": "Límite ± por canal vs gasto base, p.ej. 0.6."},
            "mode": {"type": "string", "enum": ["free", "anchored"], "description": "free = bolsa libre; anchored = cada unidad conserva su gasto base."},
            "unit_min_m": {"type": "object", "description": "Mínimo por unidad, p.ej. {'Food Delivery': 120}."},
            "unit_max_m": {"type": "object"},
            "medio_min_m": {"type": "object", "description": "Mínimo por medio sumando ambas unidades, p.ej. {'TV': 100}. Medios: OOH, TV, Radio, Search, Social Media, Digital, Prensa."},
            "medio_max_m": {"type": "object"},
            "channel_min_m": {"type": "object", "description": "Mínimo por canal usando ID (C01..C17)."},
            "channel_max_m": {"type": "object"},
            "fixed_m": {"type": "object", "description": "Canales con gasto fijo {ID: M MXN}."},
            "value_factor": {"type": "object", "description": "Factor de valor por unidad (1 = revenue; usar margen si DiDi lo entrega)."},
            "breakeven_mroi": {"type": "number", "description": "Umbral de MROI definido por el usuario. No inventarlo."}}}}},
    {"type": "function", "function": {
        "name": "run_sensitivity",
        "description": "Sensibilidad del óptimo al exponente c de cada unidad (±0.05, ±0.10), con los mismos límites.",
        "parameters": {"type": "object", "properties": {k: {"type": "object"} for k in ("unit_min_m", "medio_min_m")} | {"limit_pct": {"type": "number"}, "mode": {"type": "string", "enum": ["free", "anchored"]}}}}},
    {"type": "function", "function": {
        "name": "list_curves",
        "description": "Lista las 17 curvas con ID, unidad, medio, gasto base, ROI y MROI base.",
        "parameters": {"type": "object", "properties": {}}}},
]


def _cfg_from_args(df, a: dict):
    cfg = service.default_cfg()
    if a.get("total_m"): cfg["total"] = a["total_m"] * M
    if a.get("limit_pct") is not None: cfg["limit_pct"] = float(a["limit_pct"])
    cfg["mode"] = a.get("mode", "free")
    for src, dst in (("unit_min_m", "unit_min"), ("unit_max_m", "unit_max"), ("medio_min_m", "medio_min"), ("medio_max_m", "medio_max"),
                     ("channel_min_m", "channel_min"), ("channel_max_m", "channel_max"), ("fixed_m", "fixed")):
        cfg[dst] = {k: v * M for k, v in (a.get(src) or {}).items()}
    cfg["factor"] = a.get("value_factor") or {}
    if a.get("breakeven_mroi") is not None: cfg["alerts"]["breakeven_mroi"] = a["breakeven_mroi"]
    return cfg


def _tbl(df_):
    return json.loads(df_.round(4).to_json(orient="records", force_ascii=False))


def dispatch(df, name: str, args: dict | None):
    args = args or {}
    try:
        if name == "list_curves":
            b = service.evaluate(df, df.x0.values)
            return json.dumps({"curvas": _tbl(b.assign(x0_m=b.x0 / M)[["id", "bu", "ch", "det", "x0_m", "roi", "mroi"]])}, ensure_ascii=False)
        cfg = _cfg_from_args(df, args)
        if name == "run_scenario":
            r = service.run(df, cfg); us = r["unit_opt"]
            ch = r["opt"].assign(gasto_m=r["opt"].x / M, base_m=r["opt"].x0 / M)[["id", "label", "base_m", "gasto_m", "cambio_pct", "mroi", "estado"]]
            return json.dumps({"presupuesto_m": r["total"] / M, "metodo": r["info"]["method"], "lambda": r["info"]["lambda"],
                               "unidades": json.loads((us / M).round(3).assign(cambio_gasto_pct=us.cambio_gasto_pct.round(4)).reset_index().to_json(orient="records", force_ascii=False)),
                               "valor_total_m": r["opt"].rev.sum() / M, "valor_base_m": r["base"].rev.sum() / M,
                               "uplift_pct": r["opt"].rev.sum() / r["base"].rev.sum() - 1, "canales": _tbl(ch), "alertas": r["alerts"]}, ensure_ascii=False)
        if name == "run_sensitivity":
            lo, hi = service._bounds(df, cfg); s = sensitivity_c(df, cfg["total"] or df.x0.sum(), lo, hi, cfg["factor"], service._groups(df, cfg), cfg["mode"] == "anchored")
            return json.dumps({"filas": _tbl(s), "rango_uplift": [float(s.uplift_vs_plan.min()), float(s.uplift_vs_plan.max())]}, ensure_ascii=False)
        return json.dumps({"error": f"herramienta desconocida: {name}"})
    except Exception as e:  # el modelo debe ver el motivo (p.ej. restricciones incompatibles) y explicarlo
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
