"""
LexEC — Scraper de Leyes Aprobadas
Fuente: leyes.asambleanacional.gob.ec
Descarga solo leyes con estado "Publicado" (en el Registro Oficial).
Corre todos los días a las 7 AM (Ecuador) via GitHub Actions.
"""
import os, re, json, time, requests, csv, io
from datetime import date, datetime
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

ASAMBLEA_URL = "https://leyes.asambleanacional.gob.ec/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "es-EC,es;q=0.9",
    "Referer": "https://leyes.asambleanacional.gob.ec/",
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
    """Verifica si una ley con ese título ya está guardada."""
    # Buscar por los primeros 80 caracteres del título
    titulo_corto = titulo[:80]
    data = sb_get("normas", params={
        "titulo": f"ilike.*{titulo_corto[:40]}*",
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

# ── Obtener leyes publicadas de la Asamblea ───────────────

def obtener_leyes_publicadas():
    """
    Descarga el listado de leyes con estado 'Publicado'
    desde leyes.asambleanacional.gob.ec.
    Usa la exportación CSV del sitio — sin necesidad de Playwright.
    """
    leyes = []

    # El sitio permite exportar todos los registros a CSV
    # Filtramos por fase = "Publicado" directamente en la URL
    params_busqueda = {
        "fase": "Publicado",    # solo leyes publicadas en el RO
        "exportar": "csv",      # exportar como CSV
    }

    print("  Descargando listado de leyes publicadas de la Asamblea Nacional...")

    # Intentar exportación CSV directa
    try:
        r = requests.post(
            ASAMBLEA_URL,
            headers=HEADERS,
            data={
                "txtFase": "Publicado",
                "btnBuscar": "Buscar",
                "exportCSV": "1",
            },
            timeout=30,
        )
        if r.status_code == 200 and ("Publicado" in r.text or "titulo" in r.text.lower()):
            leyes = parsear_csv_asamblea(r.text)
            if leyes:
                print(f"  CSV directo: {len(leyes)} leyes publicadas")
                return leyes
    except Exception as e:
        print(f"  CSV directo falló: {e}")

    # Si CSV no funcionó, scraping HTML con BeautifulSoup
    print("  Intentando scraping HTML...")
    leyes = scraping_html_asamblea()
    return leyes


def scraping_html_asamblea():
    """
    Scraping directo del HTML de la Asamblea.
    El sitio no tiene Cloudflare y responde normalmente.
    Filtra solo las filas con estado 'Publicado'.
    """
    leyes = []

    try:
        # Buscar solo proyectos publicados
        r = requests.post(
            ASAMBLEA_URL,
            headers=HEADERS,
            data={
                "txtFase": "Publicado",
                "btnBuscar": "Buscar",
            },
            timeout=30,
        )
        r.raise_for_status()
        print(f"  HTML recibido: {len(r.text)} caracteres")

    except Exception as e:
        print(f"  Error accediendo a la Asamblea: {e}")
        # Intentar GET simple
        try:
            r = requests.get(ASAMBLEA_URL, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e2:
            print(f"  GET también falló: {e2}")
            return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Buscar la tabla de resultados
    tabla = soup.find("table")
    if not tabla:
        print("  No se encontró tabla en el HTML")
        # Mostrar estructura para debug
        print(f"  Tags encontrados: {[t.name for t in soup.find_all()][:20]}")
        return []

    filas = tabla.find_all("tr")
    print(f"  Filas en tabla: {len(filas)}")

    for fila in filas[1:]:  # saltar encabezado
        celdas = fila.find_all(["td", "th"])
        if len(celdas) < 3:
            continue

        # Extraer texto de cada celda
        textos = [c.get_text(strip=True) for c in celdas]

        # Buscar estado "Publicado" en la fila
        fila_texto = " ".join(textos).lower()
        if "publicado" not in fila_texto:
            continue

        # Extraer título (generalmente en la segunda columna)
        titulo = ""
        for i, texto in enumerate(textos):
            if len(texto) > 20 and "ley" in texto.lower():
                titulo = texto
                break

        if not titulo:
            titulo = textos[1] if len(textos) > 1 else textos[0]

        # Extraer fecha
        fecha_str = None
        for texto in textos:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", texto)
            if m:
                fecha_str = m.group(1)
                break

        # Extraer número de RO si aparece
        numero_ro = None
        for texto in textos:
            m = re.search(r"RO\s*(?:N[°º.]?\s*)?(\d+)", texto, re.I)
            if m:
                numero_ro = f"RO N° {m.group(1)}"
                break

        # Buscar link a documentos
        link = fila.find("a", href=True)
        url_detalle = ""
        if link:
            href = link["href"]
            url_detalle = href if href.startswith("http") else f"https://leyes.asambleanacional.gob.ec{href}"

        if titulo and len(titulo) > 10:
            leyes.append({
                "titulo": titulo,
                "fecha": fecha_str or str(date.today()),
                "numero_ro": numero_ro,
                "url": url_detalle,
            })
            print(f"  Ley publicada: {titulo[:70]}")

    return leyes


def parsear_csv_asamblea(contenido_csv):
    """Parsea el CSV exportado por la Asamblea."""
    leyes = []
    try:
        reader = csv.DictReader(io.StringIO(contenido_csv))
        for row in reader:
            estado = row.get("Estado", row.get("estado", "")).lower()
            if "publicado" not in estado:
                continue

            titulo = row.get("Proyecto", row.get("proyecto", row.get("Titulo", "")))
            fecha  = row.get("Fecha de Presentación", row.get("fecha", ""))
            codigo = row.get("Código", row.get("codigo", ""))

            if titulo:
                leyes.append({
                    "titulo": titulo.strip(),
                    "fecha": fecha.strip() if fecha else str(date.today()),
                    "numero_ro": None,
                    "url": f"{ASAMBLEA_URL}?cod={codigo}" if codigo else "",
                })
    except Exception as e:
        print(f"  Error parseando CSV: {e}")
    return leyes


# ── Obtener PDF de una ley aprobada ───────────────────────

def obtener_pdf_ley(url_detalle, titulo):
    """
    Busca el PDF del texto aprobado en la página de detalle de la ley.
    La Asamblea publica el 'Texto aprobado por el Pleno' y el 'Registro Oficial'.
    """
    if not url_detalle:
        return None, None

    try:
        r = requests.get(url_detalle, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Buscar link al Registro Oficial o texto aprobado
        prioridades = ["registro oficial", "texto aprobado", "texto definitivo", "publicado"]

        for prioridad in prioridades:
            for a in soup.find_all("a", href=True):
                texto_link = a.get_text(strip=True).lower()
                href = a["href"]
                if prioridad in texto_link and (".pdf" in href.lower() or "pdf" in texto_link):
                    url_pdf = href if href.startswith("http") else f"https://leyes.asambleanacional.gob.ec{href}"
                    print(f"    PDF encontrado ({prioridad}): {url_pdf[:60]}")
                    return url_pdf, prioridad

        # Si no encontró por prioridad, tomar cualquier PDF
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                url_pdf = a["href"] if a["href"].startswith("http") else f"https://leyes.asambleanacional.gob.ec{a['href']}"
                return url_pdf, "pdf"

    except Exception as e:
        print(f"    Error buscando PDF: {e}")

    return None, None


def extraer_texto_pdf(url_pdf):
    """Descarga y extrae el texto de un PDF."""
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
            print(f"    Texto extraído: {len(texto)} caracteres")
            return texto.strip()

    except Exception as e:
        print(f"    Error extrayendo PDF: {e}")

    return None


# ── Clasificador Gemini ───────────────────────────────────

TEMATICAS = [
    "Tributario","Laboral","Penal","Civil","Ambiental","Salud","Educación",
    "Financiero","Administrativo","Constitucional","Comercial","Familia",
    "Contratación Pública","Seguridad Social","Telecomunicaciones",
    "Energía","Transporte","Agricultura","Minería","Otro",
]

def clasificar_ley(titulo, texto=None):
    """
    Clasifica una ley usando Gemini.
    Si hay texto disponible lo usa; si no, solo el título.
    """
    contenido = texto[:3000] if texto else f"Título de la ley: {titulo}"

    prompt = f"""Analiza esta ley ecuatoriana aprobada por la Asamblea Nacional.
Responde SOLO con JSON válido, sin markdown ni texto extra.

CONTENIDO:
{contenido}

JSON:
{{
  "jerarquia": "Ley Orgánica o Ley Ordinaria",
  "tematica": "una de: {' | '.join(TEMATICAS)}",
  "vigencia": "Vigente",
  "sumario": "resumen de 2-3 oraciones del contenido principal de la ley"
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
        d   = json.loads(raw)
        return d
    except Exception as e:
        print(f"    Gemini error: {e}")
        # Fallback: determinar jerarquía por el título
        jerarquia = "Ley Orgánica" if "orgánica" in titulo.lower() or "organica" in titulo.lower() else "Ley Ordinaria"
        return {
            "jerarquia": jerarquia,
            "tematica": "Otro",
            "vigencia": "Vigente",
            "sumario": f"Ley aprobada por la Asamblea Nacional del Ecuador: {titulo}",
        }

def extraer_arts(texto, n=5):
    arts = []
    if not texto:
        return arts
    for m in re.finditer(
        r"Art[íi]culo?\s*\.?\s*(\d+)[°º.]?\s*[-–]?\s*([^\n]{15,250})",
        texto, re.I
    ):
        arts.append(f"Art. {m.group(1)}: {m.group(2).strip()}")
        if len(arts) >= n:
            break
    return arts


# ── Pipeline principal ────────────────────────────────────

def procesar_ley(ley):
    """Procesa una ley: obtiene PDF, clasifica y guarda en Supabase."""
    titulo = ley["titulo"]

    if ya_existe(titulo):
        print(f"  [{titulo[:50]}...] Ya existe.")
        return 0

    print(f"\n  Procesando: {titulo[:70]}...")

    # Buscar PDF del texto aprobado
    url_pdf, tipo_pdf = obtener_pdf_ley(ley.get("url", ""), titulo)

    # Extraer texto del PDF
    texto = None
    if url_pdf:
        texto = extraer_texto_pdf(url_pdf)

    # Clasificar con Gemini
    clasificacion = clasificar_ley(titulo, texto)
    articulos     = extraer_arts(texto) if texto else []

    # Construir registro para Supabase
    norma = {
        "titulo":       titulo,
        "numero_ro":    ley.get("numero_ro"),
        "numero_norma": None,
        "jerarquia":    clasificacion.get("jerarquia", "Ley Orgánica"),
        "origen":       "Asamblea Nacional",
        "tematica":     clasificacion.get("tematica", "Otro"),
        "vigencia":     "Vigente",
        "fecha_pub":    ley.get("fecha") or str(date.today()),
        "url_pdf":      url_pdf,
        "sumario":      clasificacion.get("sumario"),
        "articulos":    articulos if articulos else None,
        "metodo_ocr":   "asamblea_nacional",
    }

    try:
        sb_insert("normas", norma)
        print(f"  ✓ Guardada: [{norma['jerarquia']}] [{norma['tematica']}] {titulo[:55]}")
        return 1
    except Exception as e:
        print(f"  ✗ Error guardando: {e}")
        log("ERROR", f"Error guardando {titulo[:60]}", {"error": str(e)})
        return 0


# ── Main ──────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"LexEC — Scraper Asamblea Nacional — {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")
    log("INFO", f"Iniciado — {inicio.strftime('%Y-%m-%d %H:%M')}")

    # Obtener leyes publicadas
    leyes = obtener_leyes_publicadas()

    if not leyes:
        msg = "No se encontraron leyes publicadas nuevas."
        print(f"\n{msg}")
        log("INFO", msg)
        return

    print(f"\n  Total leyes publicadas encontradas: {len(leyes)}")
    print(f"  Procesando solo las que no están en la BD...\n")

    total = 0
    for ley in leyes:
        try:
            total += procesar_ley(ley)
            time.sleep(0.5)  # pausa cortés entre requests
        except Exception as e:
            print(f"  Error en {ley.get('titulo', '?')[:40]}: {e}")
            log("ERROR", str(e))

    seg = (datetime.now() - inicio).seconds
    msg = f"Completado: {total} leyes nuevas guardadas en {seg}s"
    print(f"\n{msg}")
    log("INFO", msg, {"leyes_nuevas": total, "segundos": seg})


if __name__ == "__main__":
    main()
