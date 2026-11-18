# DiDi · Calculadora de Budget Allocation (México) – v1

## Abrir la app
**👉 [Abrir la app]([https://.streamlit.app](https://didimex.streamlit.app/))**  
[![Abrir en Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://REEMPLAZA-CON-TU-SUBDOMINIO.streamlit.app)

> Después de desplegar, Streamlit te da la URL (en *Advanced settings* puedes elegir el subdominio). Reemplaza `REEMPLAZA-CON-TU-SUBDOMINIO` en estas dos líneas (botón de lápiz en GitHub) y haz commit. Si la app tiene `APP_PASSWORD`, pedirá contraseña al abrir.


Calculadora + interfaz + asistente opcional sobre las 17 curvas de respuesta (MMM RideShare y Food Delivery).
**Un solo motor determinista** alimenta la interfaz, el Excel exportado y las herramientas del asistente.

## Arranque
```bash
pip install -r requirements-dev.txt
python -m pytest tests -q          # 22 pruebas: reproduce el PDF y valida las restricciones
streamlit run app.py
```

## Qué hace
- Presupuesto compartido (por defecto 323.4 M; editable) y límite ± por canal (por defecto ±60%, PDF › Metodología §3).
- **Mínimos y máximos** por canal (curva), por línea de negocio y por medio (TV, Search, Social… sumando ambas unidades), y canales fijos.
- Modos: **bolsa libre** o **unidad anclada** (cada unidad conserva su gasto base).
- Tres escenarios: plan actual, propuesta manual de la mesa y óptimo. Mix por medio. Factor de valor por unidad (1 = revenue; margen cuando DiDi lo entregue).
- Alertas (rango, extrapolación, límites activos, restricciones de medio/unidad, propuesta no óptima, cambio material por unidad, umbral de MROI, comparabilidad de c, curvas sin reentrenar).
- Sensibilidad al exponente c y frontera de reparto entre unidades. Exportación a Excel.
- Pestaña "Asistente": LLM que llama al mismo motor (opcional).

## Cómo resuelve
Revenue = f·a / (1 + (x/b)^c), c<0 (b = columna "ICP B" del Excel). Con −1<c<0 el problema es convexo: el óptimo es único.
- Sin límites de medio: solución exacta por bisección sobre λ (MROI de equilibrio); los límites por unidad se resuelven exactamente fijando la unidad en su límite.
- Con límites por medio (cruzan unidades): SLSQP con gradiente analítico, con verificación previa de factibilidad (LP) y de violación. Si no hay solución, la app explica que las restricciones son incompatibles.
- Las pruebas verifican: cifras del PDF (1,113.1 M; Food 101.9 / Ride 221.5), condiciones de optimalidad (MROI igual en canales interiores), contra un solver independiente y con multi-start en el caso con límites de medio.

## Asistente con LLM (opcional)
Define `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (variables de entorno o `.streamlit/secrets.toml`). Sirve cualquier API compatible con OpenAI y con soporte de *tool calling*.
- Hay proveedores con capa gratuita y endpoint compatible, y se puede correr un modelo local (p. ej. Ollama). **Verifica vigencia, límites y términos de cada uno.**
- **Datos:** con una API externa, el gasto y los resultados viajan al proveedor. Confirma la política de datos de DiDi/OMNI antes de usar cifras reales; si no se puede, usa un modelo local o deja el asistente apagado (la interfaz no lo necesita).
- `llm_agent.py` no se probó contra un proveedor real en el entorno de construcción (sin red). El despacho de herramientas (`agent_tools.py`) sí está probado.
- Las herramientas: `run_scenario`, `run_sensitivity`, `list_curves`. Todo monto en millones de MXN.

## Despliegue (a validar con TI/seguridad del cliente)
Local o servidor interno es lo más simple para datos confidenciales. Un hosting público gratuito (p. ej. Streamlit Community Cloud) implica que el código y los datos de curvas viven fuera del entorno del cliente; revisa privacidad y acceso antes.

## Límites del modelo (declarados en la propuesta)
Revenue ≠ margen; sin sinergias ni canibalización; solo México; las curvas operan en régimen de potencia (x/b ≤ 2.8e-7), por lo que a y b no se identifican por separado y los exponentes vienen de una malla de transformaciones: la magnitud del uplift es sensible a c (ver pestaña Sensibilidad).

## Estructura
`engine.py` motor · `service.py` config→resultados y alertas · `app.py` Streamlit · `agent_tools.py` herramientas LLM · `llm_agent.py` cliente · `data/` curvas · `tests/`

## Estilo (OM Design System)
Tema en `.streamlit/config.toml` (claro y oscuro con los tokens semánticos del design system) y capa visual en `theme.py` (Instrument Sans con fallback Arial, banner con gradiente "ground dark", badges de alerta con las reglas de contraste, sin sombras). El logo no se redibuja: copia el asset oficial a `assets/logo_white.svg` (o `.png`) y se mostrará solo.

## Despliegue desde GitHub (Streamlit Community Cloud)
1. Crea un repositorio **privado** en GitHub y sube el proyecto:
   ```bash
   cd didi_budget_app
   git init -b main && git add . && git commit -m "DiDi budget allocation v1"
   git remote add origin https://github.com/<org>/<repo>.git && git push -u origin main
   ```
   `.gitignore` ya excluye `.streamlit/secrets.toml`; nunca subas claves.
2. Entra a https://share.streamlit.io con tu cuenta de GitHub → **Create app** → elige repo, rama `main` y archivo `app.py`.
3. En **Advanced settings → Secrets** pega (solo lo que uses):
   ```toml
   APP_PASSWORD = "<contraseña de acceso>"
   LLM_BASE_URL = "https://<proveedor>/v1"
   LLM_API_KEY  = "<clave>"
   LLM_MODEL    = "<modelo con tool calling>"
   ```
4. Deploy. Cada `git push` a `main` redespliega. En **Settings → Sharing** revisa quién puede ver la app (las opciones vigentes pueden cambiar).
5. Si la URL es pública, define `APP_PASSWORD` (la app pide contraseña antes de mostrar cifras).

**Antes de subir cifras reales:** el repo contiene las curvas del cliente (`data/Curvas_DiDi_MX.xlsx`) y la app corre en infraestructura de terceros. Confirma con DiDi/OMNI que está permitido; si no, usa el `Dockerfile` en un servidor interno (`docker build -t didi-alloc . && docker run -p 8501:8501 didi-alloc`) o `streamlit run app.py` local.
