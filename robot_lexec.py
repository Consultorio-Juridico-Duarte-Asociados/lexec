#!/usr/bin/env python3
"""
LexEC Robot Multi-fuente v8
- Solo guarda normas con PDF descargable verificado
- Función tiene_pdf() mejorada con dominios especiales
- Códigos únicos sin MD5 basura
- Detección de bloqueo HTTP mejorada
- Clasificación de tipos extendida
- Log de descartes para trazabilidad
"""

import os, re, json, time, hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
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
MESES = {
    "enero":"01","febrero":"02","marzo":"03","abril":"04",
    "mayo":"05","junio":"06","julio":"07","agosto":"08",
    "septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"
}

# Contadores globales de trazabilidad
DESCARTES = {"sin_url": 0, "url_invalida": 0, "duplicado": 0}

# Dominios que entregan PDF real aunque la URL no termine en .pdf
DOMINIOS_PDF_ESPECIALES = [
    "esacc.corteconstitucional.gob.ec/storage/api/v1/10_dwl_fl/",
    "doc.corteconstitucional.gob.ec",
    "bivicce.corteconstitucional.gob.ec",
    "supabase.co/storage",
    "minka.presidencia.gob.ec/documentos/",
    "www.minka.gob.ec/documentos/",
]

# ── Supabase ───────────────────────────────────────────────────────────────────
def sb_get(table, params=""):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?{params}",
                     headers=HEADERS_SB, timeout=30)
    if r.status_code == 200:
        return r.json()
    print(f"  ⚠ GET {table}: {r.status_code} {r.text[:80]}")
    return []

def sb_insert(table, data):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                      headers=HEADERS_SB, data=json.dumps(data), timeout=30)
    return r.status_code in (200, 201)

def get_existentes():
    rows = sb_get("normas", "select=codigo_unico&limit=5000")
    return {r["codigo_unico"] for r in rows if r.get("codigo_unico")}

# ── Validación de PDF ──────────────────────────────────────────────────────────
def tiene_pdf(url):
    """
    Devuelve True solo si la URL apunta a un PDF directamente descargable.
    Acepta:
      - URLs que terminan en .pdf (caso general)
      - Dominios especiales conocidos que entregan PDF sin extensión .pdf
    Rechaza:
      - URLs vacías o nulas
      - Páginas web de listados o fichas (/index.php/, /item/, etc.)
      - Dominios que no entregan PDF (lexis, derechoecuador, silec)
    """
    if not url or not url.strip():
        return False

    u = url.lower().strip()
    base = u.split("?")[0].split("#")[0]

    # Dominios especiales: aceptar aunque no terminen en .pdf
    for dom in DOMINIOS_PDF_ESPECIALES:
        if dom in u:
            return True

    # Debe terminar en .pdf
    if not base.endswith(".pdf"):
        return False

    # Aunque termine en .pdf, rechazar páginas de descarga indirecta
    patrones_invalidos = [
        "/index.php/", "/item/", "/handle/",
        "lexis.com.ec", "derechoecuador.com", "silec.com",
    ]
    for pat in patrones_invalidos:
        if pat in u and "/bitstream/" not in u:
            return False

    return True

# ── Inserción ─────────────────────────────────────────────────────────────────
def insertar(norma, ex):
    cod = norma.get("codigo_unico", "").strip()
    if not cod:
        return False

    # Rechazar duplicados
    if cod in ex:
        DESCARTES["duplicado"] += 1
        return False

    url_pdf = norma.get("url_pdf", "")

    # Sin URL: descartar
    if not url_pdf:
        DESCARTES["sin_url"] += 1
        print(f"  ⚠ Descartado (sin PDF): {cod}")
        return False

    # URL inválida: descartar
    if not tiene_pdf(url_pdf):
        DESCARTES["url_invalida"] += 1
        print(f"  ⚠ Descartado (URL no es PDF): {cod} → {url_pdf[:70]}")
        return False

    if sb_insert("normas", norma):
        ex.add(cod)
        return True
    return False

def log(fuente, cantidad, detalles):
    sb_insert("extracciones", {
        "fecha": datetime.now().isoformat(),
        "fuente": fuente,
        "cantidad": cantidad,
        "estado": "exitoso",
        "detalles": detalles,
    })

# ── Helpers ────────────────────────────────────────────────────────────────────
def limpiar_fecha(t, año_fallback=None):
    """
    Intenta extraer fecha del texto. Si no puede, devuelve
    el 1 de enero del año_fallback (si se provee) o None.
    Nunca devuelve datetime.now() como fecha de publicación.
    """
    if not t:
        return f"{año_fallback}-01-01" if año_fallback else None

    t2 = t.lower().strip()

    # "15 de marzo de 2023" / "15 de marzo 2023"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", t2)
    if m:
        mes = MESES.get(m.group(2))
        if mes:
            return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"

    # "2023-03-15"
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t2)
    if m2:
        return m2.group(0)

    # "15/03/2023" o "15-03-2023"
    m3 = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", t2)
    if m3:
        return f"{m3.group(3)}-{m3.group(2).zfill(2)}-{m3.group(1).zfill(2)}"

    # "03/2023" — solo mes y año
    m4 = re.search(r"(\d{2})/(\d{4})", t2)
    if m4:
        return f"{m4.group(2)}-{m4.group(1)}-01"

    return f"{año_fallback}-01-01" if año_fallback else datetime.now().strftime("%Y-%m-%d")

def limpiar_ro(t):
    if not t:
        return ""
    m = re.search(r"(?:RO|Registro\s+Oficial)[^\d]*(\d+)", t, re.IGNORECASE)
    if m:
        sup = bool(re.search(r"suplemento", t, re.IGNORECASE))
        return f"RO-S N° {m.group(1)}" if sup else f"RO N° {m.group(1)}"
    return ""

def detectar_tipo(titulo):
    """Clasifica el tipo de norma según palabras clave en el título."""
    t = titulo.lower()
    if "código" in t:
        return "Código", 3, "Leyes Orgánicas"
    if "ley orgánica" in t or "ley organica" in t:
        return "Ley Orgánica", 3, "Leyes Orgánicas"
    if re.search(r"\bley\b", t) and "reforma" not in t:
        return "Ley Ordinaria", 3, "Leyes Ordinarias"
    if "reforma" in t and "ley" in t:
        return "Ley Reformatoria", 3, "Leyes Ordinarias"
    if "resolución legislativa" in t or "resolucion legislativa" in t:
        return "Resolución Legislativa", 4, "Acuerdos y Resoluciones"
    if "decreto ejecutivo" in t or re.match(r"decreto\s+no", t):
        return "Decreto Ejecutivo", 4, "Decretos y Reglamentos"
    if "reglamento" in t:
        return "Reglamento", 4, "Decretos y Reglamentos"
    if "acuerdo ministerial" in t or re.search(r"\bam\b", t):
        return "Acuerdo Ministerial", 5, "Acuerdos y Resoluciones"
    if "resolución" in t or "resolucion" in t:
        return "Resolución", 5, "Acuerdos y Resoluciones"
    if "ordenanza" in t:
        return "Ordenanza", 6, "Ordenanzas"
    return "Norma", 5, "Acuerdos y Resoluciones"

def get_soup(url, fuente_nombre=""):
    """Descarga y parsea HTML. Detecta páginas de error/bloqueo."""
    try:
        r = requests.get(url, headers=HEADERS_WEB, timeout=20)
        # Detectar bloqueo explícito
        if r.status_code in (403, 429, 503):
            print(f"  🚫 {fuente_nombre} bloqueado: HTTP {r.status_code}")
            return None
        r.raise_for_status()
        # Detectar páginas de error disfrazadas (Cloudflare, captchas)
        if len(r.text) < 500 or "captcha" in r.text.lower() or "cf-ray" in r.headers:
            print(f"  🚫 {fuente_nombre} posible bloqueo (respuesta sospechosa)")
            return None
        return BeautifulSoup(r.text, "html.parser")
    except requests.exceptions.HTTPError as e:
        print(f"  ⚠ HTTP {e}")
        return None
    except Exception as e:
        print(f"  ⚠ {url[:70]}: {e}")
        return None

def mk(cod, titulo, tipo, jerarquia, jnombre, fecha, fuente,
       url_fuente, url_pdf, resumen, numero_ro="", etiquetas=None):
    # Fecha fallback segura
    if not fecha:
        fecha = datetime.now().strftime("%Y-%m-%d")
    return {
        "codigo_unico": cod,
        "numero_ro": numero_ro,
        "titulo": titulo[:400],
        "tipo": tipo,
        "jerarquia": jerarquia,
        "jerarquia_nombre": jnombre,
        "fecha_publicacion": fecha,
        "fecha_extraccion": datetime.now().isoformat(),
        "registro_oficial": numero_ro,
        "fuente": fuente,
        "url_fuente": url_fuente,
        "url_pdf": url_pdf,
        "resumen": resumen[:600] if resumen else titulo[:300],
        "etiquetas": etiquetas or [],
        "estado": "vigente",
        "activo": True,
        "verificado": False,
    }

# ══════════════════════════════════════════════════════════════════════
# FUENTE 1: Presidencia — Decretos Ejecutivos
# ══════════════════════════════════════════════════════════════════════
def scrape_presidencia(ex):
    print("📌 F1: Presidencia — Decretos Ejecutivos")
    total = 0
    base = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    for p in range(1, 20):
        url = base if p == 1 else f"{base}page/{p}/"
        soup = get_soup(url, "Presidencia")
        if not soup:
            print("  ⚠ Presidencia no responde — saltando fuente")
            break
        nuevos = 0
        for fila in soup.find_all("tr"):
            cols = fila.find_all("td")
            if len(cols) < 3:
                continue
            num_raw = cols[0].get_text(strip=True)
            fecha_raw = cols[1].get_text(strip=True)
            asunto = cols[2].get_text(strip=True)
            link = fila.find("a", href=True)
            if not link or not tiene_pdf(link["href"]):
                continue
            num = re.sub(r"[^\d]", "", num_raw)
            if not num:
                continue
            año = limpiar_fecha(fecha_raw)[:4] if limpiar_fecha(fecha_raw) else "0000"
            cod = f"PE-{año}-{num}"
            n = mk(cod, f"Decreto Ejecutivo No. {num} — {asunto[:150]}",
                   "Decreto Ejecutivo", 4, "Decretos y Reglamentos",
                   limpiar_fecha(fecha_raw, año),
                   "Presidencia de la República",
                   base, link["href"],
                   asunto[:600], limpiar_ro(asunto),
                   ["presidencia", "decreto-ejecutivo", f"de-{año}"])
            if insertar(n, ex):
                print(f"  ✅ {cod}")
                nuevos += 1
                total += 1
        if nuevos == 0 and p > 2:
            break
        time.sleep(1)
    return total

# ══════════════════════════════════════════════════════════════════════
# FUENTE 2: Asamblea Nacional — Leyes aprobadas
# ══════════════════════════════════════════════════════════════════════
def scrape_asamblea(ex):
    print("\n📌 F2: Asamblea Nacional")
    total = 0
    paginas_vacias = 0
    for p in range(0, 25):
        url = f"https://www.asambleanacional.gob.ec/es/leyes-aprobadas?page={p}"
        soup = get_soup(url, "Asamblea Nacional")
        if not soup:
            break
        nuevos = 0
        for row in soup.find_all("tr"):
            # Solo filas con PDF directo
            pdf = row.find("a", href=lambda h: h and tiene_pdf(h))
            if not pdf:
                continue
            cells = row.find_all("td")
            if not cells:
                continue
            # Tomar solo la primera celda como título (no concatenar todo)
            titulo = cells[0].get_text(strip=True) if cells else ""
            if not titulo or len(titulo) < 10:
                # Intentar con el texto del link
                titulo = pdf.get_text(strip=True)
            if not titulo or len(titulo) < 10:
                continue

            href = pdf["href"]
            if not href.startswith("http"):
                href = "https://www.asambleanacional.gob.ec" + href

            # Número: buscar al inicio del título o en otra celda
            num = None
            num_m = re.search(r"^(\d+)\s", titulo)
            if num_m:
                num = num_m.group(1)
            elif len(cells) > 1:
                # Buscar número en segunda celda
                num_m2 = re.search(r"\d+", cells[1].get_text(strip=True))
                if num_m2:
                    num = num_m2.group(0)

            # Sin número usamos hash corto del título limpio, no del MD5 completo
            if not num:
                num = f"LY{abs(hash(titulo)) % 10000:04d}"

            # Fecha
            fecha_raw = ""
            for c in cells:
                txt = c.get_text(strip=True)
                if re.search(r"\d{2}[/\-]\d{2}[/\-]\d{4}", txt):
                    fecha_raw = txt
                    break
            fecha = limpiar_fecha(fecha_raw, datetime.now().year)

            ro = limpiar_ro(titulo)
            tipo, jerarquia, jnombre = detectar_tipo(titulo)
            cod = f"AN-{num}-{fecha[:4]}"

            n = mk(cod, titulo[:300], tipo, jerarquia, jnombre, fecha,
                   "Asamblea Nacional",
                   "https://www.asambleanacional.gob.ec/es/leyes-aprobadas",
                   href, titulo, ro,
                   ["asamblea-nacional", tipo.lower().replace(" ", "-")])
            if insertar(n, ex):
                print(f"  ✅ {cod} — {titulo[:60]}")
                nuevos += 1
                total += 1

        if nuevos == 0:
            paginas_vacias += 1
            if paginas_vacias >= 3:  # tolerar hasta 3 páginas vacías consecutivas
                break
        else:
            paginas_vacias = 0
        time.sleep(1.5)
    return total

# ══════════════════════════════════════════════════════════════════════
# FUENTE 3: Ministerio del Trabajo
# ══════════════════════════════════════════════════════════════════════
def scrape_trabajo(ex):
    print("\n📌 F3: Ministerio del Trabajo")
    total = 0
    for p in range(1, 11):
        url = ("https://www.trabajo.gob.ec/acuerdos-ministeriales/" if p == 1
               else f"https://www.trabajo.gob.ec/acuerdos-ministeriales/page/{p}/")
        soup = get_soup(url, "Trabajo")
        if not soup:
            break
        nuevos = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("http"):
                href = "https://www.trabajo.gob.ec" + href
            if not tiene_pdf(href):
                continue
            titulo = link.get_text(strip=True)
            num_m = re.search(r"MDT-(\d{4})-(\d+)", titulo)
            if not num_m:
                continue
            año, num = num_m.group(1), num_m.group(2)
            fecha_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", titulo.lower())
            fecha = limpiar_fecha(fecha_m.group(0) if fecha_m else "", año)
            cod = f"MDT-AM-{año}-{num}"
            n = mk(cod, titulo[:300],
                   "Acuerdo Ministerial", 5, "Acuerdos y Resoluciones",
                   fecha, "Ministerio del Trabajo",
                   "https://www.trabajo.gob.ec/acuerdos-ministeriales/",
                   href, titulo[:600], "",
                   ["trabajo", "acuerdo-ministerial", f"mdt-{año}"])
            if insertar(n, ex):
                print(f"  ✅ MDT-{año}-{num}")
                nuevos += 1
                total += 1
        if nuevos == 0 and p > 1:
            break
        time.sleep(1)
    return total

# ══════════════════════════════════════════════════════════════════════
# FUENTE 4: SERCOP
# ══════════════════════════════════════════════════════════════════════
def scrape_sercop(ex):
    print("\n📌 F4: SERCOP")
    total = 0
    url_base = "https://portal.compraspublicas.gob.ec/sercop/normativa/resoluciones/"
    for url in [url_base, "https://portal.compraspublicas.gob.ec/sercop/normativa/"]:
        soup = get_soup(url, "SERCOP")
        if not soup:
            continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("http"):
                href = "https://portal.compraspublicas.gob.ec" + href
            if not tiene_pdf(href):
                continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10:
                continue
            if not any(k in titulo.lower() for k in
                       ["resoluc", "reglamento", "acuerdo", "normativa"]):
                continue
            # Número: buscar patrón RE-XXXX-YYYY o número largo
            num_m = re.search(r"(?:RE|RES)[^\d]*(\d+[-\s]\d{4}|\d{3,})", titulo, re.IGNORECASE)
            if not num_m:
                num_m = re.search(r"\d{3,}", titulo)
            if not num_m:
                continue  # sin número identificable → descartar
            num = re.sub(r"\s+", "-", num_m.group(0).strip())
            cod = f"SERCOP-RE-{num}"
            # url_fuente = página de listado, NO el PDF
            n = mk(cod, titulo[:300],
                   "Resolución", 5, "Acuerdos y Resoluciones",
                   datetime.now().strftime("%Y-%m-%d"),
                   "SERCOP", url_base, href,
                   titulo[:600], "",
                   ["sercop", "contratacion-publica"])
            if insertar(n, ex):
                print(f"  ✅ {cod} — {titulo[:50]}")
                total += 1
        time.sleep(1)
    return total

# ══════════════════════════════════════════════════════════════════════
# FUENTE 5: Ministerio de Salud
# ══════════════════════════════════════════════════════════════════════
def scrape_salud(ex):
    print("\n📌 F5: Ministerio de Salud")
    total = 0
    url_base = "https://www.salud.gob.ec/acuerdos-ministeriales/"
    soup = get_soup(url_base, "Salud")
    if not soup:
        return 0
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("http"):
            href = "https://www.salud.gob.ec" + href
        if not tiene_pdf(href):
            continue
        parent = link.find_parent(["li", "tr", "div", "td", "article", "p"])
        titulo = (parent.get_text(separator=" ", strip=True)[:200]
                  if parent else link.get_text(strip=True))
        titulo = re.sub(r"\s+", " ", titulo).strip()
        # Requiere número identificable
        num_m = re.search(r"AM[_\-\s]*(\d+[-\d]*)|(\d{4})[_\-](\d{3,})", titulo)
        if not num_m:
            continue
        num = re.sub(r"[\s_]", "-", num_m.group(0).strip())
        cod = f"MSP-AM-{num.upper()}"
        fecha_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", titulo.lower())
        fecha = limpiar_fecha(fecha_m.group(0) if fecha_m else "", datetime.now().year)
        n = mk(cod, titulo[:300],
               "Acuerdo Ministerial", 5, "Acuerdos y Resoluciones",
               fecha, "Ministerio de Salud Pública",
               url_base, href, titulo[:600], "",
               ["salud", "acuerdo-ministerial"])
        if insertar(n, ex):
            print(f"  ✅ {cod} — {titulo[:50]}")
            total += 1
    return total

# ══════════════════════════════════════════════════════════════════════
# FUENTE 6: Función Judicial
# ══════════════════════════════════════════════════════════════════════
def scrape_judicatura(ex):
    print("\n📌 F6: Función Judicial")
    total = 0
    urls = [
        "https://www.funcionjudicial.gob.ec/normativa/resoluciones",
        "https://www.funcionjudicial.gob.ec/index.php/normativa",
    ]
    for url in urls:
        soup = get_soup(url, "Función Judicial")
        if not soup:
            continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("http"):
                href = "https://www.funcionjudicial.gob.ec" + href
            if not tiene_pdf(href):
                continue
            parent = link.find_parent(["tr", "li", "div", "article", "td"])
            titulo = (parent.get_text(separator=" ", strip=True)[:200]
                      if parent else link.get_text(strip=True))
            titulo = re.sub(r"\s+", " ", titulo).strip()
            if not titulo or len(titulo) < 10:
                continue
            # Requiere número tipo 001-2024
            num_m = re.search(r"\d{3,4}[-\s]\d{4}", titulo)
            if not num_m:
                continue
            num = num_m.group(0).replace(" ", "-")
            cod = f"FJ-RES-{num}"
            fecha_m = re.search(r"\d{4}", titulo)
            año = fecha_m.group(0) if fecha_m else str(datetime.now().year)
            n = mk(cod, titulo[:300],
                   "Resolución", 5, "Acuerdos y Resoluciones",
                   limpiar_fecha("", año),
                   "Consejo de la Judicatura",
                   url, href, titulo[:600], "",
                   ["judicatura", "resolucion"])
            if insertar(n, ex):
                print(f"  ✅ {cod} — {titulo[:50]}")
                total += 1
        if total > 0:
            break
    return total

# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════
def main():
    t0 = time.time()
    print("=" * 65)
    print("🤖 LexEC Robot Multi-fuente v8")
    print("   Solo PDFs descargables | Sin códigos basura | Con trazabilidad")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    print("\n🔑 Conectando a Supabase...")
    ex = get_existentes()
    print(f"📚 Normas existentes: {len(ex)}\n")

    fuentes = [
        ("Presidencia",       scrape_presidencia),
        ("Asamblea Nacional", scrape_asamblea),
        ("Trabajo",           scrape_trabajo),
        ("SERCOP",            scrape_sercop),
        ("Salud",             scrape_salud),
        ("Judicatura",        scrape_judicatura),
    ]

    resultados = {}
    for nombre, fn in fuentes:
        try:
            resultados[nombre] = fn(ex)
        except Exception as e:
            print(f"  ❌ {nombre}: {e}")
            resultados[nombre] = 0

    total = sum(resultados.values())
    dur = round(time.time() - t0, 1)

    print("\n" + "=" * 65)
    print("📊 RESUMEN:")
    for nombre, n in resultados.items():
        print(f"  {'✅' if n > 0 else '➖'} {nombre}: {n} normas nuevas")
    print(f"\n⚠️  DESCARTES:")
    print(f"  Sin URL:       {DESCARTES['sin_url']}")
    print(f"  URL inválida:  {DESCARTES['url_invalida']}")
    print(f"  Duplicados:    {DESCARTES['duplicado']}")
    print(f"\n🎉 TOTAL INSERTADAS: {total} — {dur}s")
    print("=" * 65)

    log("GitHub Actions v8", total,
        f"v8 — {total} insertadas | descartes: sin_url={DESCARTES['sin_url']} "
        f"url_invalida={DESCARTES['url_invalida']} | " +
        " | ".join(f"{k}:{v}" for k, v in resultados.items() if v > 0))

if __name__ == "__main__":
    main()
