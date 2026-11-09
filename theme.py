"""Capa visual OM Design System: tipografía Instrument Sans (fallback Arial), banner con gradiente 'ground dark',
badges de alerta con contraste según las reglas (naranja/cian con texto oscuro; rojo con etiqueta en negrita).
Sin sombras, solo los gradientes permitidos, radios 8/16 px. El logo no se redibuja: se muestra solo si existe assets/logo_white.*"""
import os
import streamlit as st

PALETTE = {"plan": "#595959", "manual": "#5e76e8", "optimo": "#be2a97"}
MARK_MINMAX = "background-color:#ff672e;color:#15132a;font-weight:600"
MARK_FIJO = "background-color:#e8e8e8;color:#15132a"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&display=swap');
html, body, .stApp, [data-testid="stSidebar"], button, input, textarea, select { font-family: 'Instrument Sans', Arial, system-ui, sans-serif !important; }
h1, h2, h3 { font-weight: 700 !important; letter-spacing: -0.01em; }
h4, h5 { font-weight: 600 !important; }
a { text-decoration: underline; }
.om-hero { background: linear-gradient(110deg, #15132a 0%, #1c174a 81%); color: #ffffff; border-radius: 16px; padding: 28px 32px; margin-bottom: 16px; }
.om-hero .om-eyebrow { font-size: 12px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; color: #c9c6e6; margin: 0 0 6px 0; }
.om-hero h1 { color: #ffffff; font-size: 40px; line-height: 46px; margin: 0; padding: 0; }
.om-hero .om-accent { background: linear-gradient(110deg, #be2a97, #5e76e8); -webkit-background-clip: text; background-clip: text; color: transparent; }
.om-hero p { color: #c9c6e6; font-size: 14px; line-height: 20px; margin: 8px 0 0 0; max-width: 900px; }
.om-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-weight: 700; font-size: 12px; letter-spacing: .03em; margin-right: 8px; }
.om-red { background: #f71735; color: #ffffff; }
.om-amber { background: #ff672e; color: #15132a; }
.om-info { background: #00ccf6; color: #15132a; }
.om-alert { padding: 6px 0; }
</style>
"""

def apply(title_a: str, title_b: str, subtitle: str):
    st.markdown(CSS, unsafe_allow_html=True)
    logo = next((p for p in (os.path.join(os.path.dirname(__file__), "assets", n) for n in ("logo_white.svg", "logo_white.png")) if os.path.exists(p)), None)
    if logo: st.image(logo, width=120)
    st.markdown(f'<div class="om-hero"><p class="om-eyebrow">Omnicom Media · Propuesta DiDi México</p>'
                f'<h1>{title_a} <span class="om-accent">{title_b}</span></h1><p>{subtitle}</p></div>', unsafe_allow_html=True)

LABEL = {"rojo": ("om-red", "CRÍTICA"), "ámbar": ("om-amber", "REVISAR"), "info": ("om-info", "INFO")}

def alert_html(level: str, text: str) -> str:
    cls, lab = LABEL[level]
    return f'<div class="om-alert"><span class="om-badge {cls}">{lab}</span>{text}</div>'
