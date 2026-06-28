import requests
import re
import os
import json
from bs4 import BeautifulSoup
import time
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────
# robot_presidencia.py — Robot de Decretos de la Presidencia
# Compatible con el schema real de LexEC (tabla normas v8)
# Añade deduplicación por codigo_unico antes de insertar
# ─────────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS_SB = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}
HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
}

FUENTES = [
    "https://www.presidencia.gob.ec/decretos-ejecutivos/",
    "https://www.presidencia.gob.ec/resoluciones/",
]

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}


def limpiar_fecha(texto_fecha):
    """Convierte texto como '10 de abril 2026' a formato ISO '2026-04-10'.
    Devuelve None si no puede parsear (mejor que una fecha incorrecta)."""
    if not texto_fecha:
        return None
    try:
        t = texto_fecha.lower().strip()

        # "10 de abril de 2026" / "10 de abril 2026"
        m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", t)
        if m:
            mes = MESES.get(m.group(2))
            if mes and len(m.group(3)) == 4:
                return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"

        # "10/04/2026" o "10-04-2026"
        m2 = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", t)
        if m2:
            return f"{m2.group(3)}-{m2.group(2).zfill(2)}-{m2.group(1).zfill(2)}"

        # Formato ISO "2026-04-10"
        m3 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        if m3:
            return m3.group(0)

    except Exception as e:
        print(f"   Error procesando fecha '{texto_fecha}': {e}")

    return None  # Mejor NULL que fecha incorrecta


def limpiar_numero_ro(texto):
    """Extrae y formatea el número de Registro Oficial."""
    if not texto:
        return ""
    m = re.search(r"(?:RO|Registro\s+Oficial)[^\d]*(\d+)", texto, re.IGNORECASE)
    if m:
        es_suplemento = bool(re.search(r"suplemento", texto, re.IGNORECASE))
        return f"RO-S N° {m.group(1)}" if es_suplemento else f"RO N° {m.group(1)}"
    return ""


def get_existentes():
    """Obtiene el set de codigos_unico ya en la BD para deduplicar."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/normas?select=codigo_unico&limit=5000",
        headers=HEADERS_SB, timeout=30
    )
    if r.status_code == 200:
        return {row["codigo_unico"] for row in r.json() if row.get("codigo_unico")}
    print(f"  ⚠ No se pudo obtener existentes: {r.status_code}")
    return set()


def sb_insert(data):
    """Inserta una norma en Supabase."""
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/normas",
        headers=HEADERS_SB,
        data=json.dumps(data),
        timeout=30,
    )
    return r.status_code in (200, 201)


def procesar_pagina(url, tipo_jerarquia, existentes):
    """Procesa una página de decretos/resoluciones y retorna el número de nuevos."""
    print(f"--- Escaneando: {url} ---")

    try:
        r = requests.get(url, headers=HEADERS_WEB, timeout=30)
        # Detectar bloqueo
        if r.status_code in (403, 429, 503):
            print(f"   🚫 Bloqueado HTTP {r.status_code} — saltando página")
            return 0
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        filas = soup.find_all("tr")
        nuevos = 0

        for fila in filas:
            cols = fila.find_all("td")
            if len(cols) < 3:
                continue

            num_raw = cols[0].get_text(strip=True)
            fecha_raw = cols[1].get_text(strip=True)
            asunto_raw = cols[2].get_text(strip=True)
            link = fila.find("a", href=True)

            # Validar: requiere número, link y PDF
            if not num_raw or num_raw == "No." or not link:
                continue
            href = link["href"]
            if ".pdf" not in href.lower():
                continue

            # Normalizar número (quitar texto, dejar solo dígitos y guiones)
            num_limpio = re.sub(r"[^\d\-]", "", num_raw).strip("-")
            if not num_limpio:
                continue

            # Construir codigo_unico compatible con robot_lexec.py
            fecha_iso = limpiar_fecha(fecha_raw)
            año = fecha_iso[:4] if fecha_iso else "0000"

            if "decretos" in url:
                codigo = f"PE-{año}-{num_limpio}"
                tipo = "Decreto Ejecutivo"
                titulo = f"Decreto Ejecutivo No. {num_limpio}"
            else:
                codigo = f"PE-RES-{año}-{num_limpio}"
                tipo = "Resolución"
                titulo = f"Resolución No. {num_limpio} — Presidencia"

            if asunto_raw:
                titulo = f"{titulo} — {asunto_raw[:150]}"

            # Deduplicar
            if codigo in existentes:
                continue

            n_ro = limpiar_numero_ro(asunto_raw)

            norma = {
                "codigo_unico":       codigo,
                "numero_ro":          n_ro,
                "titulo":             titulo[:400],
                "tipo":               tipo,
                "jerarquia":          4,
                "jerarquia_nombre":   "Decretos y Reglamentos",
                "fecha_publicacion":  fecha_iso,  # puede ser None → NULL en BD
                "fecha_extraccion":   datetime.now().isoformat(),
                "registro_oficial":   n_ro,
                "fuente":             "Presidencia de la República",
                "url_fuente":         url,
                "url_pdf":            href,
                "resumen":            asunto_raw[:600] if asunto_raw else titulo[:300],
                "etiquetas":          ["presidencia", tipo.lower().replace(" ", "-"), f"de-{año}"],
                "estado":             "vigente",
                "activo":             True,
                "verificado":         False,
            }

            if sb_insert(norma):
                existentes.add(codigo)
                print(f"   ✓ {codigo} | {fecha_iso or 'sin fecha'} | {n_ro or 'sin RO'}")
                nuevos += 1

        return nuevos

    except Exception as e:
        print(f"Error técnico en {url}: {e}")
        return 0


def ejecutar_sincronizacion():
    print("=" * 65)
    print("🤖 Robot Presidencia — Schema v8 (compatible con LexEC)")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    print("\n🔑 Cargando normas existentes para deduplicar...")
    existentes = get_existentes()
    print(f"   {len(existentes)} normas ya en la BD\n")

    total_general = 0
    for base_url in FUENTES:
        tipo = "Decreto Ejecutivo" if "decretos" in base_url else "Resolución"
        for p in range(1, 6):  # máximo 5 páginas por fuente
            u = base_url if p == 1 else f"{base_url}page/{p}/"
            conteo = procesar_pagina(u, tipo, existentes)
            total_general += conteo
            if conteo == 0 and p > 1:
                break
            time.sleep(2)

    print(f"\n--- Sincronización Finalizada ---")
    print(f"Total de nuevos documentos en LexEC: {total_general}")


if __name__ == "__main__":
    ejecutar_sincronizacion()
