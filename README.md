# DiDi · Calculadora de Budget Allocation (México)

## Abrir la app

**👉 [Abrir la app](https://didimex.streamlit.app)**

[![Abrir en Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://didimex.streamlit.app)

Reparte un presupuesto de medios compartido entre **RideShare** y **Food Delivery** (México) para maximizar el revenue incremental, usando las 17 curvas de respuesta de los MMM existentes. Un solo motor determinista alimenta la interfaz, el Excel exportado y las herramientas del asistente.

## Cómo usarla

1. Abre el enlace de arriba. Si la app tiene contraseña, escríbela.
2. En la barra lateral, **sube el archivo de curvas** (`Curvas_DiDi_MX.xlsx`). Los datos del cliente no viven en este repositorio: se cargan en cada sesión.
3. Define los supuestos en la barra lateral: presupuesto total, límite ± por canal (por defecto ±60%), modo de reparto, mínimos y máximos por línea de negocio y factor de valor por unidad.
4. En **Canales y límites** ajusta mínimos y máximos por canal y por medio, fija canales y escribe la propuesta manual de la mesa.
5. Revisa **Resultados** (plan actual vs propuesta manual vs óptimo), **Alertas** y **Sensibilidad y reparto**.
6. En **Exportar**, descarga el escenario en Excel.

### Formato del archivo de curvas

Excel o CSV con las columnas del modelo: `Category`, `Curve name`, `Curve Detail`, `Annual Spend of the Curve`, `A`, `C`, `ICP B` y `Annual Incremental KPI Due to @ Historic Spend`. Se requiere `A > 0`, `ICP B > 0`, `C < 0` y gasto base > 0.

## Qué hace

- Presupuesto compartido (por defecto, el gasto base total) y límite ± por canal.
- **Mínimos y máximos** por canal (curva), por línea de negocio y por medio (TV, Search, Social… sumando ambas unidades), y canales fijos.
- Modos: **bolsa libre** o **unidad anclada** (cada unidad conserva su gasto base).
- Tres escenarios lado a lado, mix por medio y factor de valor por unidad (1 = revenue; margen cuando DiDi lo entregue).
- Alertas: rango, extrapolación, límites activos, restricciones de medio o unidad, propuesta no óptima, cambio material por unidad, umbral de MROI, comparabilidad de `c` y curvas sin reentrenar.
- Sensibilidad al exponente `c` y frontera de reparto entre unidades.
- Asistente opcional con LLM que llama al mismo motor.

## Cómo resuelve

Revenue = f · a / (1 + (x/b)^c), con c < 0 (b = columna `ICP B`). Con −1 < c < 0 el problema es convexo y el óptimo es único.

- Sin límites de medio: solución exacta por bisección sobre λ (el MROI de equilibrio). Los límites por unidad se resuelven exactamente fijando la unidad en su límite.
- Con límites por medio (cruzan unidades): SLSQP con gradiente analítico, con verificación previa de factibilidad. Si las restricciones son incompatibles, la app lo explica.

## Datos y confidencialidad

- Este repositorio es **código solamente**: no incluye el Excel de curvas ni cifras del cliente. No lo agregues mientras el repo sea público.
- Las curvas que subes se procesan en la sesión de la app, que corre en la infraestructura de Streamlit Community Cloud. Confirma con DiDi y OMNI que está permitido antes de usar cifras reales.
- Si la política no lo permite, corre la app en local o en un servidor interno (ver abajo).

## Asistente con LLM (opcional)

Define `LLM_BASE_URL`, `LLM_API_KEY` y `LLM_MODEL` (en los *Secrets* de Streamlit o como variables de entorno). Sirve cualquier API compatible con OpenAI y con soporte de *tool calling*. Herramientas: `run_scenario`, `run_sensitivity`, `list_curves` (montos en millones de MXN).

Con una API externa, el gasto y los resultados viajan al proveedor: confirma la política de datos antes de usarla con cifras reales. La interfaz funciona completa sin el asistente.

## Correr en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

En Windows, si `python` no se reconoce, usa `py -m pip install -r requirements.txt` y `py -m streamlit run app.py`.

## Despliegue

App desplegada en Streamlit Community Cloud desde este repositorio: rama `main`, archivo `app.py`, Python 3.12.

En **Settings → Secrets** de la app (opcionales):

```toml
APP_PASSWORD = "<contraseña de acceso>"
LLM_BASE_URL = "https://<proveedor>/v1"
LLM_API_KEY  = "<clave>"
LLM_MODEL    = "<modelo con tool calling>"
```

Con `APP_PASSWORD` definido, la app pide contraseña antes de mostrar cifras. Cada `git push` a `main` redespliega.

## Límites del modelo

Revenue no es margen; no hay sinergias ni canibalización entre unidades; solo México. Las curvas operan en régimen de potencia (x/b ≤ 2.8e-7), por lo que `a` y `b` no se identifican por separado y los exponentes vienen de una malla de transformaciones del Model Builder: la magnitud del uplift es sensible a `c` (ver pestaña Sensibilidad).

## Estructura

`app.py` interfaz · `engine.py` motor · `service.py` configuración → resultados y alertas · `theme.py` estilo OM · `agent_tools.py` y `llm_agent.py` asistente · `requirements.txt` dependencias · `.streamlit/config.toml` tema
