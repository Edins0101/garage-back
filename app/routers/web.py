"""Páginas públicas (sin /api): el enlace de invitación y la verificación de App Links.

WhatsApp y la mayoría de los chats solo vuelven tocables los enlaces http/https, así que las
invitaciones se comparten como https://…/join/CODIGO. Si Arianna está instalada, Android abre
el enlace directo en la app (App Links, verificado con assetlinks.json). Si no, se ve esta
página con el código y un botón para abrir la app.
"""

import re
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter(include_in_schema=False)

_CODE = re.compile(r"[A-Za-z0-9]{4,12}")


@router.get("/.well-known/assetlinks.json")
def assetlinks():
    settings = get_settings()
    fingerprints = [f.strip() for f in settings.android_cert_sha256.split(",") if f.strip()]
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": settings.android_package,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]


@router.get("/join/{code}", response_class=HTMLResponse)
def join_page(code: str):
    if not _CODE.fullmatch(code):
        return HTMLResponse(_page("Enlace no válido", "<p>Revisa el enlace o pide un código nuevo.</p>"), status_code=404)
    code = escape(code.upper())
    package = escape(get_settings().android_package)
    # intent:// abre la app en Chrome; si no está instalada vuelve a esta página.
    intent = f"intent://join/{code}#Intent;scheme=arianna;package={package};end"
    body = f"""
      <p>Te invitaron a Arianna. Tu código es:</p>
      <div class="code">{code}</div>
      <a class="btn" href="{intent}">Abrir en Arianna</a>
      <p class="hint">Si no se abre, entra a Arianna, toca <b>Unirme</b> y escribe el código.
      ¿Aún no tienes la app? Pídesela a quien te invitó.</p>"""
    return _page("Únete en Arianna", body)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta property="og:title" content="{title}">
<meta property="og:description" content="Abre el enlace para unirte en Arianna.">
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#1b1530; color:#f4f0ff; font-family:system-ui, sans-serif; }}
  main {{ max-width:360px; padding:32px 20px; text-align:center; }}
  h1 {{ font-size:28px; letter-spacing:2px; margin:0 0 8px; }}
  .code {{ font-size:40px; font-weight:700; letter-spacing:8px; margin:16px 0 24px; color:#c9b6ff; }}
  .btn {{ display:block; padding:16px; border-radius:16px; background:#7c5cff; color:#fff;
          text-decoration:none; font-weight:600; font-size:18px; }}
  .hint {{ color:#b8afd6; font-size:14px; line-height:1.5; margin-top:24px; }}
</style></head>
<body><main><h1>A✦RIANNA</h1>{body}</main></body></html>"""
