"""Asistente opcional: cualquier API compatible con OpenAI (chat.completions + tools).
Configurar por variables de entorno o st.secrets: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
NOTA: no probado contra un proveedor real en este entorno (sin acceso a red); el despacho de herramientas sí está probado."""
from __future__ import annotations
import json, os
import requests
from agent_tools import TOOL_SPECS, dispatch

SYSTEM = """Eres un especialista senior en MMM y optimización de medios que apoya a la mesa de planificación de DiDi México (RideShare y Food Delivery).
REGLAS: (1) Toda cifra debe venir de una herramienta; nunca calcules ni estimes por tu cuenta. (2) Para cualquier escenario llama run_scenario; antes de recomendar un reparto entre unidades llama run_sensitivity y reporta el rango. (3) Revenue no es margen; no inventes márgenes, umbrales ni metas: pídelos. (4) Las curvas operan en régimen de potencia (x/b <= 2.8e-7): a y b no están identificados por separado, no interpretes a como techo. (5) No recomiendes gasto fuera de ±60% del base sin marcarlo como extrapolación. (6) Si una herramienta devuelve error de restricciones incompatibles, explícalo y propone cómo relajarlas. (7) Eres consultivo: la mesa decide. Responde en el idioma del usuario, citando supuestos (presupuesto, límites, modo, factor) y alertas.
Montos de las herramientas en millones de MXN."""


def chat(df, messages, base_url=None, api_key=None, model=None, max_steps=6):
    base_url = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/"); api_key = api_key or os.getenv("LLM_API_KEY", ""); model = model or os.getenv("LLM_MODEL", "")
    if not (base_url and api_key and model):
        raise RuntimeError("Configura LLM_BASE_URL, LLM_API_KEY y LLM_MODEL.")
    msgs = [{"role": "system", "content": SYSTEM}] + messages
    for _ in range(max_steps):
        r = requests.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
                          json={"model": model, "messages": msgs, "tools": TOOL_SPECS, "temperature": 0.1}, timeout=90)
        r.raise_for_status(); m = r.json()["choices"][0]["message"]; msgs.append(m)
        if not m.get("tool_calls"):
            return m.get("content", ""), msgs[1:]
        for tc in m["tool_calls"]:
            out = dispatch(df, tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
    return "Se alcanzó el máximo de pasos de herramientas.", msgs[1:]
