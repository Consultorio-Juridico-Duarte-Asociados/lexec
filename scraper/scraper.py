"""
LexEC — Scraper Automático del Registro Oficial del Ecuador
Usa múltiples métodos para encontrar nuevas ediciones.
"""

import os, re, json, time, requests
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
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

# ── Búsqueda de ediciones recientes ──────────────────────

def obtener_ediciones():
    """
    Intenta múltiples métodos para encontrar ediciones recientes.
    """
    ediciones = []

    # MÉTODO 1: Buscar en el sitio del RO con múltiples URLs
    urls = [
        "https://www.registroficial.gob.ec/registro-oficial/",
        "https://www.registroficial.gob.ec/component/k2/itemlist/category/1-registro-oficial",
        "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/registro-oficial",
    ]

    for url in urls:
        try:
            print(f"  Intentando: {url}")
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200 and len(r.text) > 1000:
                encontradas = parsear_html_ro(r.text)
                if encontradas:
                    print(f"  ✓ Método 1 encontró {len(encontradas)} ediciones")
                    ediciones.extend(encontradas)
                    break
        except Exception as e:
            print(f"  Error en {url}: {e}")

    # MÉTODO 2: Buscar PDFs directamente por número estimado
    if not ediciones:
        print("  Intentando método 2: búsqueda por número estimado...")
        ediciones = buscar_por_numero_estimado()

    # MÉTODO 3: Buscar en Google News / fuentes alternativas
    if not ediciones:
        print("  Intentando método 3: fuentes alternativas...")
        ediciones = buscar_fuentes_alternativas()

    return ediciones


def parsear_html_ro(html):
    """Extrae ediciones del HTML del Registro Oficial."""
    soup = BeautifulSoup(html, "html.parser")
    ediciones = []
    vistos = set()

    MESES = {
        "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
        "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
    }

    # Buscar cualquier link con número de RO
    for tag in soup.find_all(["a", "h2", "h3", "div", "span", "p"]):
        texto = tag.get_text(strip=True)
        href  = tag.get("href", "") if tag.name == "a" else ""

        # Patrón: número de 3-4 dígitos con fecha
        m_num = re.search(r"\b(\d{3,4})\b", texto)
        if not m_num:
            continue

        numero = m_num.group(1)
        if numero in vistos or int(numero) < 100:
            continue

        # Buscar fecha
        m_fecha = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I)
        if not m_fecha:
            continue

        try:
            dia  = int(m_fecha.group(1))
            mes  = MESES.get(m_fecha.group(2).lower(), 0)
            anio = int(m_fecha.group(3))
            if not mes or not (2024 <= anio <= 2030):
                continue
            fecha = date(anio, mes, dia)
        except Exception:
            continue

        tipo   = "suplemento" if "suplemento" in texto.lower() else "ordinario"
        num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"
        url_c  = href if href.startswith("http") else (f"https://www.registroficial.gob.ec{href}" if href else "")

        ediciones.append({
            "numero": num_ro,
            "tipo": tipo,
            "fecha": str(fecha),
            "url": url_c,
            "url_pdf": None,
        })
        vistos.add(numero)

    return ediciones


def buscar_por_numero_estimado():
    """
    Estima el número de la edición de hoy basándose en el último número conocido
    y lo busca directamente en el servidor del RO.
    """
    ediciones = []
    hoy = date.today()

    # El RO publica aprox 250 ediciones por año
    # RO N° 1 fue en 1895, estimamos el número actual
    # En 2024 estaban alrededor del N° 600-700
    # Intentamos los últimos 5 números posibles
    anio_actual = hoy.year
    numero_estimado_base = 400 + (anio_actual - 2020) * 250

    urls_base = [
        "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/suplementos/item/",
        "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/registro-oficial/item/",
    ]

    for num in range(numero_estimado_base, numero_estimado_base + 10):
        for base in urls_base:
            try:
                url = f"{base}{num}"
                r = requests.get(url, headers=HEADERS, timeout=10)
                if r.status_code == 200 and "registro oficial" in r.text.lower():
                    soup = BeautifulSoup(r.text, "html.parser")
                    titulo = soup.find("title")
                    if titulo:
                        print(f"  Encontrado: {titulo.get_text()[:60]}")
                        # Buscar PDF en la página
                        pdf_url = None
                        for a in soup.find_all("a", href=True):
                            if ".pdf" in a["href"].lower():
                                pdf_url = a["href"] if a["href"].startswith("http") else f"https://www.registroficial.gob.ec{a['href']}"
                                break
                        tipo   = "suplemento" if "suplemento" in r.url.lower() else "ordinario"
                        num_ro = f"RO-S N° {num}" if tipo == "suplemento" else f"RO N° {num}"
                        if not ya_existe(num_ro):
                            ediciones.append({
                                "numero": num_ro,
                                "tipo": tipo,
                                "fecha": str(hoy),
                                "url": url,
                                "url_pdf": pdf_url,
                            })
            except Exception:
                pass

    return ediciones


def buscar_fuentes_alternativas():
    """
    Busca en fuentes alternativas que indexan el Registro Oficial.
    """
    ediciones = []
    hoy = date.today()

    # Intentar la API de búsqueda del RO si existe
    try:
        r = requests.get(
            "https://www.registroficial.gob.ec/index.php?option=com_k2&view=itemlist&format=json&limit=5&ordering=newest",
            headers=HEADERS, timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            for item in items:
                titulo = item.get("title", "")
                m_num = re.search(r"\b(\d{3,4})\b", titulo)
                if m_num:
                    num_ro = f"RO N° {m_num.group(1)}"
                    if not ya_existe(num_ro):
                        ediciones.append({
                            "numero": num_ro,
                            "tipo": "ordinario",
                            "fecha": str(hoy),
                            "url": item.get("link", ""),
                            "url_pdf": None,
                        })
    except Exception as e:
        print(f"  API alternativa falló: {e}")

    return ediciones


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


def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        r = requests.get(url_pdf, headers=HEADERS, timeout=30)
        r.raise_for_status()
        with open("/tmp/norma.pdf", "wb") as f:
            f.write(r.content)
        doc   = fitz.open("/tmp/norma.pdf")
        texto = "".join(p.get_text("text") for p in doc)
        doc.close()
        return texto.strip() if len(texto.strip()) > 100 else None
    except Exception as e:
        print(f"    PDF error: {e}")
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
        print(f"  [{ed['numero']}] Ya existe.")
        return 0

    print(f"  [{ed['numero']}] Procesando ({ed['fecha']})...")
    texto = None

    if ed.get("url_pdf"):
        texto = extraer_texto_pdf(ed["url_pdf"])

    if not texto and ed.get("url"):
        try:
            r    = requests.get(ed["url"], headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if ".pdf" in a["href"].lower() or "download" in a["href"].lower():
                    url_pdf = a["href"] if a["href"].startswith("http") else f"https://www.registroficial.gob.ec{a['href']}"
                    texto = extraer_texto_pdf(url_pdf)
                    if texto:
                        ed["url_pdf"] = url_pdf
                        break
        except Exception as e:
            print(f"    Error buscando PDF: {e}")

    if not texto:
        print(f"    Sin texto para {ed['numero']}.")
        log("WARNING", f"Sin texto para {ed['numero']}")
        return 0

    segmentos = separar_normas(texto)
    print(f"    {len(segmentos)} normas detectadas")

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
        msg = "No se encontraron ediciones nuevas en el RO hoy."
        print(msg)
        log("INFO", msg)
        return

    total = 0
    for ed in ediciones:
        try:
            total += procesar_edicion(ed)
        except Exception as e:
            print(f"  Error en {ed.get('numero','?')}: {e}")
            log("ERROR", str(e))

    seg = (datetime.now() - inicio).seconds
    msg = f"Completado: {total} normas nuevas en {seg}s"
    print(f"\n{msg}")
    log("INFO", msg, {"normas_nuevas": total, "segundos": seg})


if __name__ == "__main__":
    main()
