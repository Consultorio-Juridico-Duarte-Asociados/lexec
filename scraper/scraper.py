"""
LexEC — Scraper via API JSON del Registro Oficial
El RO expone una API Joomla/K2 que devuelve las ediciones en JSON.
No requiere JavaScript ni navegador.
"""
import os, re, json, time, requests
from datetime import date, datetime
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

MESES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-EC,es;q=0.9",
    "Referer": "https://www.registroficial.gob.ec/",
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
            "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=representation",
        },
        json=datos, timeout=15,
    )
    r.raise_for_status()
    return r.json()

def ya_existe(numero_ro):
    data = sb_get("normas", params={"numero_ro": f"eq.{numero_ro}", "select": "id", "limit": 1})
    return len(data) > 0

def log(nivel, msg, detalle=None):
    try:
        sb_insert("scraper_logs", {"nivel": nivel, "mensaje": msg, "detalle": detalle})
    except Exception:
        pass

# ── Obtener ediciones por API JSON ────────────────────────

# URLs de la API K2/Joomla del Registro Oficial
API_URLS = [
    # API de items recientes — categorías del RO
    "https://www.registroficial.gob.ec/index.php?option=com_k2&view=itemlist&format=json&limit=10&ordering=newest&task=category&id=1",
    "https://www.registroficial.gob.ec/index.php?option=com_k2&view=itemlist&format=json&limit=10&ordering=newest",
    # API de búsqueda
    "https://www.registroficial.gob.ec/index.php?option=com_k2&view=itemlist&format=json&limit=10&tag=registro+oficial",
    # Feed RSS del sitio
    "https://www.registroficial.gob.ec/index.php?format=feed&type=rss",
    "https://www.registroficial.gob.ec/index.php?option=com_content&view=category&id=1&format=feed&type=rss",
]

def obtener_ediciones():
    ediciones = []
    encontradas_ids = set()

    # ── Método 1: APIs JSON ───────────────────────────────
    for url in API_URLS:
        try:
            print(f"  Probando: {url[:70]}")
            r = requests.get(url, headers=HEADERS, timeout=15)
            ct = r.headers.get("content-type", "")

            if "json" in ct and r.status_code == 200:
                data = r.json()
                items = data.get("items", data.get("rows", []))
                print(f"  → JSON con {len(items)} items")
                for item in items:
                    ed = parsear_item_json(item)
                    if ed and ed["numero"] not in encontradas_ids:
                        ediciones.append(ed)
                        encontradas_ids.add(ed["numero"])
                if items:
                    break

            elif "rss" in ct or "xml" in ct or r.text.strip().startswith("<?xml"):
                print(f"  → RSS/XML")
                eds = parsear_rss(r.text)
                for ed in eds:
                    if ed["numero"] not in encontradas_ids:
                        ediciones.append(ed)
                        encontradas_ids.add(ed["numero"])
                if eds:
                    break
            else:
                print(f"  → HTML (status {r.status_code}, {len(r.text)} chars)")

        except Exception as e:
            print(f"  Error: {e}")

    # ── Método 2: Playwright como último recurso ──────────
    if not ediciones:
        print("\n  Usando Playwright con scroll...")
        ediciones = obtener_con_playwright_scroll(encontradas_ids)

    print(f"\n  Total ediciones nuevas encontradas: {len(ediciones)}")
    return ediciones


def parsear_item_json(item):
    """Parsea un item de la API JSON del RO."""
    titulo = item.get("title", "") or item.get("name", "")
    url    = item.get("link", "") or item.get("url", "")
    fecha_str = item.get("created", "") or item.get("date", "")

    m_num = re.search(r"\b(\d{3,4})\b", titulo)
    if not m_num:
        return None

    numero = m_num.group(1)
    tipo   = "suplemento" if "suplemento" in titulo.lower() else "ordinario"
    num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"

    # Parsear fecha
    fecha = date.today()
    if fecha_str:
        m_f = re.search(r"(\d{4})-(\d{2})-(\d{2})", fecha_str)
        if m_f:
            try:
                fecha = date(int(m_f.group(1)), int(m_f.group(2)), int(m_f.group(3)))
            except Exception:
                pass

    if not url.startswith("http"):
        url = f"https://www.registroficial.gob.ec{url}"

    return {"numero": num_ro, "tipo": tipo, "fecha": str(fecha), "url": url, "url_pdf": None}


def parsear_rss(xml_text):
    """Parsea un feed RSS del RO."""
    ediciones = []
    soup = BeautifulSoup(xml_text, "xml")
    vistos = set()

    for item in soup.find_all("item"):
        titulo = item.find("title")
        link   = item.find("link")
        pubdate = item.find("pubDate")

        if not titulo:
            continue

        texto = titulo.get_text(strip=True)
        m_num = re.search(r"\b(\d{3,4})\b", texto)
        if not m_num or m_num.group(1) in vistos:
            continue

        numero = m_num.group(1)
        tipo   = "suplemento" if "suplemento" in texto.lower() else "ordinario"
        num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"
        url    = link.get_text(strip=True) if link else ""

        # Fecha del RSS
        fecha = date.today()
        if pubdate:
            m_f = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", pubdate.get_text())
            meses_cortos = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                            "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
            if m_f:
                try:
                    fecha = date(int(m_f.group(3)), meses_cortos.get(m_f.group(2), 1), int(m_f.group(1)))
                except Exception:
                    pass

        print(f"  RSS: {num_ro} | {fecha} | {url[:50]}")
        ediciones.append({"numero": num_ro, "tipo": tipo, "fecha": str(fecha), "url": url, "url_pdf": None})
        vistos.add(numero)

    return ediciones


def obtener_con_playwright_scroll(encontradas_ids):
    """Última opción: Playwright con scroll para cargar contenido dinámico."""
    from playwright.sync_api import sync_playwright
    ediciones = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = context.new_page()

        try:
            page.goto("https://www.registroficial.gob.ec/registro-oficial/",
                     wait_until="networkidle", timeout=30000)

            # Scroll para cargar contenido lazy
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(800)

            page.wait_for_timeout(2000)
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Buscar en TODO el HTML — texto visible e invisible
            texto_completo = soup.get_text(" ")
            print(f"  Texto extraído: {len(texto_completo)} chars")

            # Buscar todos los patrones de RO
            patrones = [
                r"(?:Registro\s+Oficial|RO)\s+(?:N[°º.]?\s*)?(\d{3,4})",
                r"(?:Suplemento|Sup\.?)\s+(?:al\s+)?(?:RO|Registro\s+Oficial)?\s*(?:N[°º.]?\s*)?(\d{3,4})",
                r"(?:Edici[oó]n\s+)?(?:N[°º.]?\s*)(\d{3,4})\s*(?:del?\s+\d)",
            ]

            vistos = set(encontradas_ids)
            for patron in patrones:
                for m in re.finditer(patron, texto_completo, re.I):
                    numero = m.group(1)
                    if numero in vistos or int(numero) < 100:
                        continue
                    # Extraer contexto alrededor del match
                    inicio = max(0, m.start() - 100)
                    fin    = min(len(texto_completo), m.end() + 100)
                    contexto = texto_completo[inicio:fin]
                    print(f"  Match: {numero} | contexto: '{contexto[:80]}'")

                    tipo   = "suplemento" if "suplemento" in contexto.lower() else "ordinario"
                    num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"

                    if not ya_existe(num_ro):
                        ediciones.append({
                            "numero": num_ro, "tipo": tipo,
                            "fecha": str(date.today()), "url": "", "url_pdf": None,
                        })
                    vistos.add(numero)

        except Exception as e:
            print(f"  Playwright error: {e}")
        finally:
            browser.close()

    return ediciones


# ── Buscar PDF de una edición ─────────────────────────────

def buscar_pdf(url_edicion):
    """Busca el PDF en la página de una edición."""
    if not url_edicion:
        return None
    try:
        r    = requests.get(url_edicion, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if ".pdf" in h.lower() or "download" in h.lower():
                return h if h.startswith("http") else f"https://www.registroficial.gob.ec{h}"
    except Exception:
        pass
    return None


def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        r = requests.get(url_pdf, headers=HEADERS, timeout=30)
        r.raise_for_status()
        with open("/tmp/norma.pdf", "wb") as f:
            f.write(r.content)
        doc   = fitz.open("/tmp/norma.pdf")
        texto = "".join(pg.get_text("text") for pg in doc)
        doc.close()
        return texto.strip() if len(texto.strip()) > 100 else None
    except Exception as e:
        print(f"    PDF error: {e}")
        return None


# ── Clasificador Gemini ───────────────────────────────────

JERARQUIAS = ["Constitución","Tratado Internacional","Ley Orgánica","Ley Ordinaria",
              "Decreto Ejecutivo","Decreto Ley","Reglamento","Ordenanza",
              "Resolución","Acuerdo Ministerial","Circular","Instructivo","Otro"]
VIGENCIAS  = ["Vigente","Derogada","Reformada","Suspendida","En vacatio legis"]
TEMATICAS  = ["Tributario","Laboral","Penal","Civil","Ambiental","Salud","Educación",
              "Financiero","Administrativo","Constitucional","Comercial","Familia",
              "Contratación Pública","Seguridad Social","Telecomunicaciones",
              "Energía","Transporte","Agricultura","Minería","Otro"]

def clasificar(texto):
    prompt = f"""Analiza esta norma legal ecuatoriana del Registro Oficial.
Responde SOLO con JSON válido, sin markdown ni texto extra.

TEXTO:
{texto[:4000]}

JSON:
{{
  "titulo": "título completo oficial",
  "numero_norma": "número oficial o null",
  "jerarquia": "uno de: {' | '.join(JERARQUIAS)}",
  "origen": "institución emisora",
  "tematica": "una de: {' | '.join(TEMATICAS)}",
  "vigencia": "uno de: {' | '.join(VIGENCIAS)}",
  "fecha_pub": "YYYY-MM-DD o null",
  "sumario": "resumen de 2-3 oraciones"
}}"""
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        d   = json.loads(raw)
        if d.get("jerarquia") not in JERARQUIAS: d["jerarquia"] = "Otro"
        if d.get("vigencia")  not in VIGENCIAS:  d["vigencia"]  = "Vigente"
        if d.get("tematica")  not in TEMATICAS:  d["tematica"]  = "Otro"
        return d
    except Exception as e:
        print(f"    Gemini error: {e}")
        return None

def extraer_arts(texto, n=5):
    arts = []
    for m in re.finditer(r"Art[íi]culo?\s*\.?\s*(\d+)[°º.]?\s*[-–]?\s*([^\n]{15,250})", texto, re.I):
        arts.append(f"Art. {m.group(1)}: {m.group(2).strip()}")
        if len(arts) >= n: break
    return arts

def separar_normas(texto):
    partes = re.split(
        r"(?=(?:DECRETO\s+(?:EJECUTIVO|LEY)|LEY\s+ORG[ÁA]NICA|LEY\s+ORDINARIA|"
        r"ACUERDO\s+MINISTERIAL|RESOLUCI[ÓO]N|ORDENANZA|REGLAMENTO|CIRCULAR|INSTRUCTIVO)\s)",
        texto, flags=re.I,
    )
    return [p.strip() for p in partes if len(p.strip()) >= 200]

def procesar_edicion(ed):
    if ya_existe(ed["numero"]):
        return 0
    print(f"\n  Procesando {ed['numero']} ({ed['fecha']})...")

    if not ed.get("url_pdf") and ed.get("url"):
        ed["url_pdf"] = buscar_pdf(ed["url"])

    texto = extraer_texto_pdf(ed["url_pdf"]) if ed.get("url_pdf") else None

    if not texto:
        log("WARNING", f"Sin texto para {ed['numero']}")
        return 0

    segmentos = separar_normas(texto)
    print(f"    {len(segmentos)} normas en esta edición")

    guardadas = 0
    for i, seg in enumerate(segmentos, 1):
        c = clasificar(seg) or {
            "titulo": f"Norma {ed['numero']} seg.{i}",
            "jerarquia": "Otro", "vigencia": "Vigente",
            "tematica": "Otro", "sumario": seg[:300],
        }
        norma = {
            "titulo":       c.get("titulo") or f"Norma {ed['numero']}",
            "numero_ro":    ed["numero"],
            "numero_norma": c.get("numero_norma"),
            "jerarquia":    c.get("jerarquia", "Otro"),
            "origen":       c.get("origen"),
            "tematica":     c.get("tematica", "Otro"),
            "vigencia":     c.get("vigencia", "Vigente"),
            "fecha_pub":    c.get("fecha_pub") or ed["fecha"],
            "url_pdf":      ed.get("url_pdf"),
            "sumario":      c.get("sumario"),
            "articulos":    extraer_arts(seg) or None,
            "metodo_ocr":   "automatico",
        }
        try:
            sb_insert("normas", norma)
            print(f"    ✓ [{norma['jerarquia']}] {norma['titulo'][:55]}")
            guardadas += 1
        except Exception as e:
            print(f"    ✗ {e}")
        time.sleep(0.4)
    return guardadas


def main():
    inicio = datetime.now()
    print(f"\n{'='*50}\nLexEC Scraper — {inicio.strftime('%Y-%m-%d %H:%M')}\n{'='*50}\n")
    log("INFO", f"Iniciado — {inicio.strftime('%Y-%m-%d %H:%M')}")

    ediciones = obtener_ediciones()
    if not ediciones:
        msg = "No se encontraron ediciones nuevas hoy."
        print(f"\n{msg}")
        log("INFO", msg)
        return

    total = 0
    for ed in ediciones:
        try:
            total += procesar_edicion(ed)
        except Exception as e:
            print(f"  Error: {e}")
            log("ERROR", str(e))

    seg = (datetime.now() - inicio).seconds
    msg = f"Completado: {total} normas nuevas en {seg}s"
    print(f"\n{msg}")
    log("INFO", msg, {"normas_nuevas": total, "segundos": seg})

if __name__ == "__main__":
    main()
