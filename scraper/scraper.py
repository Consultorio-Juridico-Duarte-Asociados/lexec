"""
LexEC — Scraper con Playwright (navegador real)
Bypasea la protección de Cloudflare del Registro Oficial.
"""
import os, re, json, time, requests
from datetime import date, datetime
from playwright.sync_api import sync_playwright

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

MESES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
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

# ── Scraping con Playwright (navegador real) ──────────────

def obtener_ediciones_playwright():
    """
    Usa un navegador real (Chromium) para cargar el Registro Oficial
    y extraer las ediciones recientes. Bypasea Cloudflare/JS.
    """
    ediciones = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-EC",
        )
        page = context.new_page()

        try:
            print("  Abriendo Registro Oficial con navegador real...")
            page.goto("https://www.registroficial.gob.ec/registro-oficial/", 
                     wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            html = page.content()
            print(f"  Página cargada: {len(html)} caracteres")

            # Extraer links de ediciones
            links = page.query_selector_all("a")
            vistos = set()

            for link in links:
                try:
                    texto = link.inner_text().strip()
                    href  = link.get_attribute("href") or ""

                    m_num = re.search(r"\b(\d{3,4})\b", texto)
                    if not m_num or m_num.group(1) in vistos:
                        continue

                    m_fecha = re.search(
                        r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I
                    )
                    if not m_fecha:
                        continue

                    dia  = int(m_fecha.group(1))
                    mes  = MESES.get(m_fecha.group(2).lower(), 0)
                    anio = int(m_fecha.group(3))
                    if not mes or not (2023 <= anio <= 2030):
                        continue

                    numero = m_num.group(1)
                    fecha  = date(anio, mes, dia)
                    tipo   = "suplemento" if "suplemento" in texto.lower() else "ordinario"
                    num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"
                    url_c  = href if href.startswith("http") else f"https://www.registroficial.gob.ec{href}"

                    ediciones.append({
                        "numero": num_ro, "tipo": tipo,
                        "fecha": str(fecha), "url": url_c, "url_pdf": None,
                    })
                    vistos.add(numero)
                    print(f"  Encontrada: {num_ro} del {fecha}")

                except Exception:
                    continue

            # Si no encontró nada, intentar navegar a la sección de publicaciones
            if not ediciones:
                print("  Intentando sección de publicaciones...")
                page.goto("https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/registro-oficial",
                         wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                links = page.query_selector_all("a[href*='item']")
                for link in links[:20]:
                    try:
                        texto = link.inner_text().strip()
                        href  = link.get_attribute("href") or ""
                        m_num = re.search(r"\b(\d{3,4})\b", texto)
                        if m_num and href and m_num.group(1) not in vistos:
                            # Visitar cada página para obtener la fecha y PDF
                            sub_page = context.new_page()
                            try:
                                url_item = href if href.startswith("http") else f"https://www.registroficial.gob.ec{href}"
                                sub_page.goto(url_item, wait_until="domcontentloaded", timeout=15000)
                                sub_page.wait_for_timeout(1500)

                                contenido = sub_page.inner_text("body")
                                m_fecha = re.search(
                                    r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", contenido, re.I
                                )
                                pdf_links = sub_page.query_selector_all("a[href*='.pdf']")
                                url_pdf = None
                                if pdf_links:
                                    url_pdf = pdf_links[0].get_attribute("href")
                                    if url_pdf and not url_pdf.startswith("http"):
                                        url_pdf = f"https://www.registroficial.gob.ec{url_pdf}"

                                if m_fecha:
                                    dia  = int(m_fecha.group(1))
                                    mes  = MESES.get(m_fecha.group(2).lower(), 0)
                                    anio = int(m_fecha.group(3))
                                    if mes and 2023 <= anio <= 2030:
                                        numero = m_num.group(1)
                                        fecha  = date(anio, mes, dia)
                                        tipo   = "suplemento" if "suplemento" in texto.lower() else "ordinario"
                                        num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"
                                        ediciones.append({
                                            "numero": num_ro, "tipo": tipo,
                                            "fecha": str(fecha), "url": url_item, "url_pdf": url_pdf,
                                        })
                                        vistos.add(numero)
                                        print(f"  Encontrada: {num_ro} del {fecha}")
                            except Exception as e:
                                print(f"    Sub-página error: {e}")
                            finally:
                                sub_page.close()
                    except Exception:
                        continue

        except Exception as e:
            print(f"  Error con Playwright: {e}")
        finally:
            browser.close()

    print(f"  Total ediciones encontradas: {len(ediciones)}")
    return ediciones


def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url_pdf, headers=headers, timeout=30)
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
        print(f"  [{ed['numero']}] Ya existe.")
        return 0

    print(f"  [{ed['numero']}] Procesando ({ed['fecha']})...")
    texto = None

    if ed.get("url_pdf"):
        texto = extraer_texto_pdf(ed["url_pdf"])

    if not texto and ed.get("url"):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r    = requests.get(ed["url"], headers=headers, timeout=20)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if ".pdf" in a["href"].lower():
                    url_pdf = a["href"] if a["href"].startswith("http") else f"https://www.registroficial.gob.ec{a['href']}"
                    texto = extraer_texto_pdf(url_pdf)
                    if texto:
                        ed["url_pdf"] = url_pdf
                        break
        except Exception as e:
            print(f"    Error buscando PDF: {e}")

    if not texto:
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
            "metodo_ocr":   "playwright",
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

    ediciones = obtener_ediciones_playwright()

    if not ediciones:
        msg = "No se encontraron ediciones nuevas hoy."
        print(msg)
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
