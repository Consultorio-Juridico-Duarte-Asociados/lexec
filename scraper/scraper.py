"""
LexEC — Scraper con Playwright
Versión con debug para ver la estructura real del sitio.
"""
import os, re, json, time, requests
from datetime import date, datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

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

# ── Extrae fecha de un texto ──────────────────────────────

def extraer_fecha(texto):
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I)
    if not m:
        return None
    try:
        dia  = int(m.group(1))
        mes  = MESES.get(m.group(2).lower(), 0)
        anio = int(m.group(3))
        if mes and 2020 <= anio <= 2030:
            return date(anio, mes, dia)
    except Exception:
        pass
    return None

# ── Scraping con Playwright ───────────────────────────────

def obtener_ediciones():
    ediciones = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-EC",
        )
        page = context.new_page()

        try:
            # ── Cargar página principal ───────────────────
            print("  Abriendo Registro Oficial...")
            page.goto(
                "https://www.registroficial.gob.ec/registro-oficial/",
                wait_until="networkidle", timeout=30000,
            )
            page.wait_for_timeout(2000)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # DEBUG: mostrar todos los textos con números de 3-4 dígitos
            print("\n  === LINKS CON NÚMEROS DETECTADOS ===")
            vistos = set()
            candidatos = []

            for tag in soup.find_all(["a", "h1", "h2", "h3", "h4", "li", "p", "span", "div"]):
                texto = tag.get_text(" ", strip=True)
                href  = tag.get("href", "") if tag.name == "a" else ""

                # Buscar número de RO
                m_num = re.search(r"(?:N[°º.]?\s*)?(\d{3,4})", texto)
                if not m_num:
                    continue

                numero = m_num.group(1)
                if numero in vistos or int(numero) < 100:
                    continue

                # Debe tener fecha o la palabra "registro"
                tiene_fecha   = bool(re.search(r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}", texto, re.I))
                tiene_ro      = bool(re.search(r"registro\s*oficial|suplemento|edici[oó]n", texto, re.I))
                tiene_enlace  = bool(href)

                if tiene_fecha or (tiene_ro and tiene_enlace):
                    print(f"  [{numero}] '{texto[:80]}' | href={href[:60]}")
                    candidatos.append({
                        "numero": numero,
                        "texto": texto,
                        "href": href,
                    })
                    vistos.add(numero)

            print(f"\n  Total candidatos: {len(candidatos)}")

            # ── Procesar candidatos ───────────────────────
            for c in candidatos:
                numero = c["numero"]
                texto  = c["texto"]
                href   = c["href"]

                fecha = extraer_fecha(texto)
                if not fecha:
                    fecha = date.today()

                tipo   = "suplemento" if "suplemento" in texto.lower() else "ordinario"
                num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"

                if ya_existe(num_ro):
                    print(f"  [{num_ro}] Ya existe.")
                    continue

                url_c = href if href.startswith("http") else (
                    f"https://www.registroficial.gob.ec{href}" if href else ""
                )

                # Buscar PDF en la página de la edición
                url_pdf = None
                if url_c:
                    try:
                        sub = context.new_page()
                        sub.goto(url_c, wait_until="domcontentloaded", timeout=15000)
                        sub.wait_for_timeout(1500)
                        sub_html = sub.content()
                        sub.close()

                        sub_soup = BeautifulSoup(sub_html, "html.parser")
                        for a in sub_soup.find_all("a", href=True):
                            if ".pdf" in a["href"].lower():
                                url_pdf = a["href"]
                                if not url_pdf.startswith("http"):
                                    url_pdf = f"https://www.registroficial.gob.ec{url_pdf}"
                                print(f"    PDF encontrado: {url_pdf[:60]}")
                                break
                    except Exception as e:
                        print(f"    Error buscando PDF: {e}")

                ediciones.append({
                    "numero": num_ro, "tipo": tipo,
                    "fecha": str(fecha), "url": url_c, "url_pdf": url_pdf,
                })
                print(f"  ✓ Edición nueva: {num_ro} del {fecha}")

            # ── Si no encontró nada, intentar URL de suplementos ──
            if not ediciones:
                print("\n  Intentando sección de suplementos...")
                page.goto(
                    "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/suplementos",
                    wait_until="networkidle", timeout=30000,
                )
                page.wait_for_timeout(2000)

                html2 = page.content()
                soup2 = BeautifulSoup(html2, "html.parser")

                for a in soup2.find_all("a", href=True):
                    texto = a.get_text(strip=True)
                    href  = a["href"]
                    m_num = re.search(r"\b(\d{3,4})\b", texto)
                    fecha = extraer_fecha(texto)

                    if m_num and fecha and m_num.group(1) not in vistos:
                        numero = m_num.group(1)
                        num_ro = f"RO-S N° {numero}"
                        url_c  = href if href.startswith("http") else f"https://www.registroficial.gob.ec{href}"
                        print(f"  Suplemento: {num_ro} | {fecha} | {url_c[:50]}")

                        if not ya_existe(num_ro):
                            ediciones.append({
                                "numero": num_ro, "tipo": "suplemento",
                                "fecha": str(fecha), "url": url_c, "url_pdf": None,
                            })
                        vistos.add(numero)

        except Exception as e:
            print(f"  Error Playwright: {e}")
        finally:
            browser.close()

    print(f"\n  Total ediciones nuevas: {len(ediciones)}")
    return ediciones


# ── Texto de PDF ──────────────────────────────────────────

def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        r = requests.get(url_pdf, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
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


# ── Pipeline ──────────────────────────────────────────────

def procesar_edicion(ed):
    if ya_existe(ed["numero"]):
        return 0

    print(f"\n  Procesando {ed['numero']} ({ed['fecha']})...")
    texto = None

    if ed.get("url_pdf"):
        texto = extraer_texto_pdf(ed["url_pdf"])

    if not texto and ed.get("url"):
        try:
            r    = requests.get(ed["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if ".pdf" in a["href"].lower():
                    url_pdf = a["href"] if a["href"].startswith("http") else f"https://www.registroficial.gob.ec{a['href']}"
                    texto = extraer_texto_pdf(url_pdf)
                    if texto:
                        ed["url_pdf"] = url_pdf
                        break
        except Exception as e:
            print(f"    Error: {e}")

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


# ── Main ──────────────────────────────────────────────────

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
