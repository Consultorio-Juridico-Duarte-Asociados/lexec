"""
LexEC — Scraper de Leyes Aprobadas
Fuente: www.asambleanacional.gob.ec/es/leyes-aprobadas
HTML estático, sin JavaScript, sin Cloudflare. Funciona perfectamente.
Corre todos los días a las 7 AM (Ecuador) via GitHub Actions.
"""
import os, re, json, time, requests
from datetime import date, datetime
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

BASE_URL    = "https://www.asambleanacional.gob.ec"
LEYES_URL   = f"{BASE_URL}/es/leyes-aprobadas"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,*/*",
    "Accept-Language": "es-EC,es;q=0.9",
}

# ── Supabase ──────────────────────────────────────────────

def sb_get(endpoint, params=None):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{endpoint}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        params=params, timeout=15,
    )
    r.raise_for_status()
    return r.json()

def sb_insert(tabla, datos):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{tabla}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=datos, timeout=15,
    )
    r.raise_for_status()
    return r.json()

def ya_existe(titulo):
    """Verifica si la ley ya está en la BD buscando por título."""
    titulo_buscar = titulo[:60].replace("'", "''")
    data = sb_get("normas", params={
        "titulo": f"ilike.*{titulo_buscar[:40]}*",
        "select": "id",
        "limit": 1,
    })
    return len(data) > 0

def log(nivel, msg, detalle=None):
    try:
        sb_insert("scraper_logs", {
            "nivel": nivel, "mensaje": msg, "detalle": detalle
        })
    except Exception:
        pass

# ── Scraping de la Asamblea Nacional ─────────────────────

def parsear_fecha_ro(texto_ro):
    """
    Parsea la fecha del Registro Oficial.
    Ejemplo: 'R.O. No. 236, Séptimo Suplemento, de 04-03-2026'
    """
    # Formato dd-mm-yyyy
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", texto_ro)
    if m:
        try:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        except Exception:
            pass
    # Formato yyyy-mm-dd
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", texto_ro)
    if m2:
        return m2.group(0)
    return str(date.today())

def extraer_numero_ro(texto_ro):
    """Extrae el número del Registro Oficial. Ej: 'R.O. No. 236' → 'RO N° 236'"""
    m = re.search(r"R\.?O\.?\s*No\.?\s*(\d+)", texto_ro, re.I)
    if m:
        suplemento = ""
        if "suplemento" in texto_ro.lower():
            suplemento = "S"
        return f"RO{suplemento} N° {m.group(1)}"
    return None

def obtener_leyes_pagina(url):
    """Obtiene las leyes de una página del listado de la Asamblea."""
    leyes = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # La tabla tiene: Nº | Nombre | Registro Oficial | Documento
        tabla = soup.find("table")
        if not tabla:
            print(f"  No se encontró tabla en {url}")
            return leyes, None

        filas = tabla.find_all("tr")
        print(f"  {len(filas)-1} leyes en esta página")

        for fila in filas[1:]:  # saltar encabezado
            celdas = fila.find_all("td")
            if len(celdas) < 3:
                continue

            numero = celdas[0].get_text(strip=True)
            titulo = celdas[1].get_text(strip=True)
            texto_ro = celdas[2].get_text(strip=True)

            # URL del PDF
            url_pdf = None
            link = celdas[3].find("a") if len(celdas) > 3 else None
            if link and link.get("href"):
                href = link["href"]
                url_pdf = href if href.startswith("http") else f"{BASE_URL}{href}"

            if titulo and len(titulo) > 10:
                leyes.append({
                    "titulo": titulo,
                    "numero_ro": extraer_numero_ro(texto_ro),
                    "fecha": parsear_fecha_ro(texto_ro),
                    "url_pdf": url_pdf,
                    "texto_ro_completo": texto_ro,
                })

        # Buscar link a la siguiente página
        siguiente = None
        nav = soup.find("a", string=re.compile(r"siguiente|next", re.I))
        if nav and nav.get("href"):
            siguiente = f"{BASE_URL}{nav['href']}" if not nav["href"].startswith("http") else nav["href"]

        return leyes, siguiente

    except Exception as e:
        print(f"  Error en {url}: {e}")
        return leyes, None

def obtener_todas_leyes_nuevas():
    """
    Recorre las páginas del listado hasta encontrar leyes ya existentes
    o llegar a la última página.
    Solo devuelve las leyes que NO están en la BD.
    """
    nuevas = []
    url_actual = LEYES_URL
    pagina = 1
    encontro_existente = False

    while url_actual and not encontro_existente:
        print(f"\n  Página {pagina}: {url_actual}")
        leyes, siguiente = obtener_leyes_pagina(url_actual)

        for ley in leyes:
            if ya_existe(ley["titulo"]):
                print(f"  Ya existe: {ley['titulo'][:55]}... → parando")
                encontro_existente = True
                break
            else:
                nuevas.append(ley)
                print(f"  Nueva: {ley['titulo'][:65]}")

        if siguiente and not encontro_existente:
            url_actual = siguiente
            pagina += 1
            time.sleep(1)  # pausa cortés
        else:
            break

    return nuevas

# ── Extracción de texto PDF ───────────────────────────────

def extraer_texto_pdf(url_pdf):
    """Descarga y extrae texto del PDF de la ley."""
    if not url_pdf:
        return None
    try:
        import fitz
        r = requests.get(url_pdf, headers=HEADERS, timeout=30)
        r.raise_for_status()
        with open("/tmp/ley.pdf", "wb") as f:
            f.write(r.content)
        doc   = fitz.open("/tmp/ley.pdf")
        texto = "".join(pg.get_text("text") for pg in doc)
        doc.close()
        if len(texto.strip()) > 100:
            print(f"    PDF: {len(texto)} chars extraídos")
            return texto.strip()
    except Exception as e:
        print(f"    Error PDF: {e}")
    return None

def extraer_arts(texto, n=5):
    if not texto:
        return []
    arts = []
    for m in re.finditer(
        r"Art[íi]culo?\s*\.?\s*(\d+)[°º.]?\s*[-–]?\s*([^\n]{15,250})",
        texto, re.I
    ):
        arts.append(f"Art. {m.group(1)}: {m.group(2).strip()}")
        if len(arts) >= n:
            break
    return arts

# ── Clasificador Gemini ───────────────────────────────────

TEMATICAS = [
    "Tributario","Laboral","Penal","Civil","Ambiental","Salud","Educación",
    "Financiero","Administrativo","Constitucional","Comercial","Familia",
    "Contratación Pública","Seguridad Social","Telecomunicaciones",
    "Energía","Transporte","Agricultura","Minería","Otro",
]

def clasificar(titulo, texto=None):
    """Clasifica la ley con Gemini. Usa el texto si está disponible."""
    contenido = texto[:3000] if texto else f"Título: {titulo}"
    prompt = f"""Analiza esta ley ecuatoriana aprobada por la Asamblea Nacional.
Responde SOLO con JSON válido, sin markdown ni texto extra.

{contenido}

JSON:
{{
  "jerarquia": "Ley Orgánica o Ley Ordinaria",
  "tematica": "una de: {' | '.join(TEMATICAS)}",
  "sumario": "resumen claro de 2-3 oraciones del contenido principal"
}}"""

    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400},
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"    Gemini error: {e}")
        # Fallback por título
        jerarquia = "Ley Orgánica" if re.search(r"org[aá]nica", titulo, re.I) else "Ley Ordinaria"
        return {
            "jerarquia": jerarquia,
            "tematica": "Otro",
            "sumario": f"Ley aprobada por la Asamblea Nacional del Ecuador: {titulo}",
        }

# ── Procesar y guardar ────────────────────────────────────

def procesar_ley(ley):
    titulo = ley["titulo"]
    print(f"\n  Procesando: {titulo[:70]}")

    # Extraer texto del PDF
    texto = extraer_texto_pdf(ley.get("url_pdf"))

    # Clasificar con Gemini
    c = clasificar(titulo, texto)
    arts = extraer_arts(texto)

    norma = {
        "titulo":       titulo,
        "numero_ro":    ley.get("numero_ro"),
        "numero_norma": None,
        "jerarquia":    c.get("jerarquia", "Ley Orgánica"),
        "origen":       "Asamblea Nacional",
        "tematica":     c.get("tematica", "Otro"),
        "vigencia":     "Vigente",
        "fecha_pub":    ley.get("fecha") or str(date.today()),
        "url_pdf":      ley.get("url_pdf"),
        "sumario":      c.get("sumario"),
        "articulos":    arts if arts else None,
        "metodo_ocr":   "asamblea_nacional",
    }

    try:
        sb_insert("normas", norma)
        print(f"  ✓ [{norma['jerarquia']}] [{norma['tematica']}] {titulo[:50]}")
        return 1
    except Exception as e:
        print(f"  ✗ Error: {e}")
        log("ERROR", f"Error guardando {titulo[:60]}", {"error": str(e)})
        return 0

# ── Main ──────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"LexEC — Asamblea Nacional — {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")
    log("INFO", f"Iniciado — {inicio.strftime('%Y-%m-%d %H:%M')}")

    print("\nObteniendo leyes aprobadas nuevas...")
    nuevas = obtener_todas_leyes_nuevas()

    if not nuevas:
        msg = "No hay leyes nuevas publicadas hoy."
        print(f"\n{msg}")
        log("INFO", msg)
        return

    print(f"\n{len(nuevas)} leyes nuevas para procesar")
    total = 0
    for ley in nuevas:
        try:
            total += procesar_ley(ley)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error: {e}")
            log("ERROR", str(e))

    seg = (datetime.now() - inicio).seconds
    msg = f"Completado: {total} leyes nuevas en {seg}s"
    print(f"\n{msg}")
    log("INFO", msg, {"leyes_nuevas": total, "segundos": seg})

if __name__ == "__main__":
    main()
