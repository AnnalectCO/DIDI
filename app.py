import io, json, os, datetime as dt
import numpy as np
import pandas as pd
import streamlit as st
from engine import load_curves, InfeasibleError, sensitivity_c, frontier
import service
import hmac
import theme

M = 1e6
st.set_page_config(page_title="DiDi · Budget Allocation MX", layout="wide")
theme.apply("Budget Allocation", "México", "Curvas de respuesta Revenue = a / (1 + (x/b)^c) de los MMM de RideShare y Food Delivery. Revenue incremental anual en MXN; no es margen salvo que cargues un factor por unidad.")

def secret(k):
    try: return st.secrets.get(k) or os.getenv(k, "")
    except Exception: return os.getenv(k, "")

_pw = secret("APP_PASSWORD")  # acceso opcional con contraseña (útil si la URL es pública)
if _pw and not st.session_state.get("auth"):
    _x = st.text_input("Contraseña de acceso", type="password")
    if _x and hmac.compare_digest(_x, _pw): st.session_state["auth"] = True; st.rerun()
    elif _x: st.error("Contraseña incorrecta.")
    st.stop()

# ------------------------------------------------------------ datos
up = st.sidebar.file_uploader("Curvas (xlsx/csv) – opcional", type=["xlsx", "csv"], help="Por defecto se usan las 17 curvas de México incluidas.")
try:
    DF = load_curves(up if up else os.path.join(os.path.dirname(__file__), "data", "Curvas_DiDi_MX.xlsx"))
except Exception as e:
    st.error(f"No se pudieron leer las curvas: {e}"); st.stop()
if DF.attrs.get("warning"): st.warning(DF.attrs["warning"])
UNITS = list(dict.fromkeys(DF.bu)); MEDIOS = list(dict.fromkeys(DF.ch)); BASE = DF.x0.sum()

# ------------------------------------------------------------ sidebar
sb = st.sidebar
sb.header("Supuestos")
total_m = sb.number_input("Presupuesto total (M MXN)", min_value=1.0, value=round(BASE / M, 2), step=5.0, help="Por defecto, el gasto base total.")
limit = sb.slider("Límite ± por canal vs gasto base", 0, 100, 60, 5, help="Propuesta inicial del PDF: ±60%. Fuera de ese rango las curvas son poco confiables.") / 100
mode = sb.radio("Modo de reparto", ["Bolsa libre", "Unidad anclada"], help="Bolsa libre: el reparto entre unidades es resultado. Unidad anclada: cada unidad conserva su gasto base y solo se optimiza dentro de ella.")
sb.subheader("Mínimos / máximos por línea de negocio (M MXN)")
unit_min, unit_max, factor = {}, {}, {}
for u in UNITS:
    ub = DF.x0[DF.bu == u].sum() / M
    c1, c2 = sb.columns(2)
    mn = c1.number_input(f"Mín {u}", min_value=0.0, value=0.0, step=5.0, key=f"umin_{u}", help=f"Base: {ub:,.1f} M. 0 = sin mínimo.")
    mx = c2.number_input(f"Máx {u}", min_value=0.0, value=0.0, step=5.0, key=f"umax_{u}", help="0 = sin máximo.")
    if mn > 0: unit_min[u] = mn * M
    if mx > 0: unit_max[u] = mx * M
sb.subheader("Valor por unidad")
for u in UNITS:
    factor[u] = sb.number_input(f"Factor de valor {u}", min_value=0.0, value=1.0, step=0.05, key=f"fac_{u}", help="1 = revenue puro. Con márgenes de contribución de DiDi, usar el margen (p.ej. 0.12).")
with sb.expander("Umbrales de alertas (los define la mesa)"):
    A = {"unit_change_alert": st.slider("Cambio por unidad que exige revisión", 5, 60, 20, 5) / 100,
         "mroi_dispersion_eps": st.number_input("Dispersión de MROI tolerada", 0.0, 1.0, 0.02, 0.01)}
    if st.checkbox("Definir umbral de equilibrio de MROI"):
        A["breakeven_mroi"] = st.number_input("MROI de equilibrio", 0.0, 10.0, 1.0, 0.05)
    cd = st.text_input("Fecha de reentrenamiento de las curvas (AAAA-MM-DD)", "")
    if cd:
        try: dt.date.fromisoformat(cd); A["curves_date"] = cd
        except ValueError: st.warning("Formato de fecha inválido.")

# ------------------------------------------------------------ pestañas
tabs = st.tabs(["Canales y límites", "Resultados", "Alertas", "Sensibilidad y reparto", "Exportar", "Asistente"])

with tabs[0]:
    st.markdown("**Mínimo y máximo por canal (curva)**, gasto fijo opcional y **propuesta manual** de la mesa. Montos en M MXN.")
    rst = st.session_state.setdefault("reset", 0)
    ed = pd.DataFrame({"ID": DF.id, "Unidad": DF.bu, "Canal": DF.ch + " – " + DF.det, "Base": DF.x0 / M,
                       "Mín": DF.x0 * (1 - limit) / M, "Máx": DF.x0 * (1 + limit) / M, "Fijo": np.nan, "Propuesta": DF.x0 / M}).round(3)
    edited = st.data_editor(ed, hide_index=True, width="stretch", key=f"ed_{limit}_{rst}",
                            disabled=["ID", "Unidad", "Canal", "Base"],
                            column_config={"Mín": st.column_config.NumberColumn(min_value=0.0, format="%.3f"), "Máx": st.column_config.NumberColumn(min_value=0.0, format="%.3f"),
                                           "Fijo": st.column_config.NumberColumn(help="Si llenas un valor, el canal queda fijo en ese gasto.", min_value=0.0, format="%.3f"),
                                           "Propuesta": st.column_config.NumberColumn(min_value=0.0, format="%.3f")})
    if st.button("Restablecer tabla"): st.session_state.reset += 1; st.rerun()
    st.markdown("**Mínimo / máximo por medio** (suma ambas unidades). Vacío = sin límite.")
    med = pd.DataFrame({"Medio": MEDIOS, "Base": [DF.x0[DF.ch == m].sum() / M for m in MEDIOS], "Mín": np.nan, "Máx": np.nan}).round(3)
    med_ed = st.data_editor(med, hide_index=True, width="stretch", disabled=["Medio", "Base"], key="med_ed",
                            column_config={"Mín": st.column_config.NumberColumn(min_value=0.0, format="%.3f"), "Máx": st.column_config.NumberColumn(min_value=0.0, format="%.3f")})

cfg = service.default_cfg()
cfg.update(total=BASE if abs(total_m - round(BASE / M, 2)) < 1e-9 else total_m * M, limit_pct=limit, mode="anchored" if mode == "Unidad anclada" else "free", unit_min=unit_min, unit_max=unit_max, factor=factor, alerts=A)
ids = list(DF.id)
for _, r in edited.iterrows():
    i = DF.id.values.tolist().index(r.ID); b = DF.x0.values[i]
    if pd.notna(r["Mín"]): cfg["channel_min"][r.ID] = float(r["Mín"]) * M
    if pd.notna(r["Máx"]): cfg["channel_max"][r.ID] = float(r["Máx"]) * M
    if pd.notna(r["Fijo"]): cfg["fixed"][r.ID] = float(r["Fijo"]) * M
    if pd.notna(r["Propuesta"]): cfg["manual"][r.ID] = float(r["Propuesta"]) * M
for _, r in med_ed.iterrows():
    if pd.notna(r["Mín"]): cfg["medio_min"][r.Medio] = float(r["Mín"]) * M
    if pd.notna(r["Máx"]): cfg["medio_max"][r.Medio] = float(r["Máx"]) * M
if mode == "Unidad anclada" and (unit_min or unit_max):
    st.sidebar.info("En modo 'Unidad anclada' se ignoran los mín/máx por unidad: cada unidad conserva su gasto base.")

try:
    R = service.run(DF, cfg)
except InfeasibleError as e:
    for t in tabs[1:5]: t.empty()
    st.error(f"Restricciones incompatibles: {e}"); st.stop()
except RuntimeError as e:
    st.error(str(e)); st.stop()

fmt = lambda s: s / M
with tabs[1]:
    opt, base, man = R["opt"], R["base"], R["manual"]
    up_pct = opt.rev.sum() / base.rev.sum() - 1; lam = np.nanmean(list(R["info"]["lambda"].values()))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valor plan actual (M)", f"{base.rev.sum()/M:,.1f}"); c2.metric("Valor propuesta manual (M)", f"{man.rev.sum()/M:,.1f}", f"{(man.rev.sum()/base.rev.sum()-1):+.2%}")
    c3.metric("Valor óptimo (M)", f"{opt.rev.sum()/M:,.1f}", f"{up_pct:+.2%}"); c4.metric("λ: valor marginal de la bolsa", f"{lam:.3f}", help="MROI de equilibrio: lo que devolvería un peso adicional de presupuesto compartido.")
    st.caption(f"Método: {R['info']['method']}. Presupuesto {R['total']/M:,.1f} M; límites ±{limit:.0%}; modo {mode.lower()}.")
    comp = pd.concat({"Plan actual": R["unit_opt"][["gasto_base", "valor_base"]].rename(columns={"gasto_base": "gasto", "valor_base": "valor"}),
                      "Propuesta manual": R["unit_manual"][["gasto", "valor"]], "Óptimo": R["unit_opt"][["gasto", "valor"]]}, axis=1).div(M).round(2)
    comp.columns = [f"{a} · {b}" for a, b in comp.columns]
    st.subheader("Comparativo por línea de negocio (M MXN)"); st.dataframe(comp, width="stretch")
    chart = pd.DataFrame({"Plan actual": R["unit_opt"].gasto_base, "Propuesta manual": R["unit_manual"].gasto, "Óptimo": R["unit_opt"].gasto}).drop("Total") / M
    st.bar_chart(chart, color=[theme.PALETTE["plan"], theme.PALETTE["manual"], theme.PALETTE["optimo"]])
    st.subheader("Detalle por canal")
    det = pd.DataFrame({"ID": opt.id, "Canal": opt.label, "Base (M)": base.x / M, "Manual (M)": man.x / M, "Óptimo (M)": opt.x / M, "Cambio óptimo": opt.cambio_pct,
                        "MROI base": opt.mroi0, "MROI óptimo": opt.mroi, "Estado": opt.estado}).round(3)
    st.dataframe(det.style.map(lambda v: theme.MARK_MINMAX if v in ("MIN", "MAX") else (theme.MARK_FIJO if v == "FIJO" else ""), subset=["Estado"]).format({"Cambio óptimo": "{:+.1%}"}), width="stretch", hide_index=True)
    st.subheader("Mix por medio (óptimo)"); mm = R["medio_opt"].copy(); mm[["gasto_base", "gasto", "valor"]] /= M
    st.dataframe(mm.round(3).style.format({"pct_mix": "{:.1%}", "cambio_pct": "{:+.1%}"}), width="stretch")

with tabs[2]:
    n = {k: sum(a["nivel"] == k for a in R["alerts"]) for k in ("rojo", "ámbar", "info")}
    st.markdown(f"**{n['rojo']} críticas · {n['ámbar']} a revisar · {n['info']} informativas**")
    for a in R["alerts"]: st.markdown(theme.alert_html(a["nivel"], a["alerta"]), unsafe_allow_html=True)
    if not R["alerts"]: st.success("Sin alertas.")

with tabs[3]:
    st.markdown("Sensibilidad del óptimo al exponente **c** de cada unidad (recalibrando b para conservar el revenue base) y frontera de reparto entre unidades. Usa los mismos límites y restricciones de arriba.")
    lo, hi = R["lo"], R["hi"]; groups = R["groups"]
    if st.button("Calcular sensibilidad y frontera"):
        with st.spinner("Optimizando 25 combinaciones de c…"):
            st.session_state["sens"] = sensitivity_c(DF, R["total"], lo, hi, factor, groups, mode == "Unidad anclada")
            st.session_state["front"] = frontier(DF, R["total"], lo, hi, factor, groups)
    if "sens" in st.session_state:
        s = st.session_state["sens"].copy(); u1, u2 = UNITS
        st.write(f"**Uplift vs plan:** {s.uplift_vs_plan.min():+.2%} a {s.uplift_vs_plan.max():+.2%} · **Gasto {u1}:** {s['gasto_'+u1].min()/M:,.1f}–{s['gasto_'+u1].max()/M:,.1f} M · **Gasto {u2}:** {s['gasto_'+u2].min()/M:,.1f}–{s['gasto_'+u2].max()/M:,.1f} M")
        base_f = DF.x0[DF.bu == u1].sum(); flip = int((s["gasto_" + u1] > base_f).sum())
        st.write(f"En {len(s) - flip} de {len(s)} combinaciones {u1} gasta menos que hoy; en {flip} gasta más (la dirección se invierte).")
        piv = s.pivot(index=f"Δc {u2}", columns=f"Δc {u1}", values="uplift_vs_plan")
        st.caption(f"Uplift por Δc (filas: {u2}; columnas: {u1}). Δc positivo = curva más cóncava."); st.dataframe(piv.style.format("{:+.2%}"), width="stretch")
        fr = st.session_state["front"].copy()
        st.caption("Frontera: mejor valor según % de la bolsa para " + u1 + " (óptimo dentro de cada unidad).")
        st.line_chart(fr.set_index(f"pct_{u1}")["valor_total"] / M, color=theme.PALETTE["optimo"])
    else:
        st.info("Pulsa el botón para calcular (toma unos segundos).")

with tabs[4]:
    def to_xlsx():
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pd.DataFrame([{"Concepto": "Presupuesto (M MXN)", "Valor": R["total"] / M}, {"Concepto": "Límite ±", "Valor": limit}, {"Concepto": "Modo", "Valor": mode},
                          {"Concepto": "Método", "Valor": R["info"]["method"]}, {"Concepto": "Factor de valor", "Valor": json.dumps(factor)},
                          {"Concepto": "Mín unidad (M)", "Valor": json.dumps({k: v / M for k, v in unit_min.items()})}, {"Concepto": "Máx unidad (M)", "Valor": json.dumps({k: v / M for k, v in unit_max.items()})},
                          {"Concepto": "Límites por medio (M)", "Valor": json.dumps({"min": {k: v / M for k, v in cfg["medio_min"].items()}, "max": {k: v / M for k, v in cfg["medio_max"].items()}})},
                          {"Concepto": "Fecha", "Valor": dt.date.today().isoformat()}]).to_excel(w, sheet_name="Supuestos", index=False)
            comp.to_excel(w, sheet_name="Comparativo_unidades")
            det.to_excel(w, sheet_name="Detalle_canales", index=False)
            mm.to_excel(w, sheet_name="Mix_medio")
            pd.DataFrame(R["alerts"]).to_excel(w, sheet_name="Alertas", index=False)
            if "sens" in st.session_state: st.session_state["sens"].to_excel(w, sheet_name="Sensibilidad_c", index=False)
        return buf.getvalue()
    st.download_button("Descargar escenario en Excel", to_xlsx(), file_name=f"DiDi_escenario_{dt.date.today()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("Incluye supuestos, comparativo por unidad, detalle por canal, mix por medio, alertas y sensibilidad (si la calculaste).")

with tabs[5]:
    st.markdown("Asistente con LLM que **llama al mismo motor** (no calcula por su cuenta). Requiere una API compatible con OpenAI.")
    cfgd = all(secret(k) for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
    if not cfgd:
        st.info("Sin configurar. Define LLM_BASE_URL, LLM_API_KEY y LLM_MODEL (variables de entorno o .streamlit/secrets.toml). Ver README. Importante: los datos de gasto viajan al proveedor; confirma la política de datos de DiDi/OMNI antes de usarlo con cifras reales.")
    else:
        from llm_agent import chat
        hist = st.session_state.setdefault("chat", [])
        for m in hist:
            if m["role"] in ("user", "assistant") and m.get("content"): st.chat_message(m["role"]).write(m["content"])
        if q := st.chat_input("Pregunta o pide un escenario…"):
            hist.append({"role": "user", "content": q}); st.chat_message("user").write(q)
            try:
                with st.spinner("Consultando el motor…"):
                    ans, new = chat(DF, hist, secret("LLM_BASE_URL"), secret("LLM_API_KEY"), secret("LLM_MODEL"))
                st.session_state["chat"] = new; st.chat_message("assistant").write(ans)
            except Exception as e:
                st.error(f"Error del asistente: {e}")
