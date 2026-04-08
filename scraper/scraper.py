"""
LexEC — Scraper Automático del Registro Oficial del Ecuador
Corre todos los días a las 7 AM (hora Ecuador) mediante GitHub Actions.
Usa Google Gemini para clasificar (100% GRATIS — 1500 llamadas/día).
"""

import os, re, json, time, requests
from datetime import date, datetime
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (compatible; LexEC-Bot/1.0)",
    "Accept-Language": "es-EC,es;q=0.9",
}

# ── Supabase helpers ──────────────────────────────────────

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

# ── Scraping del Registro Oficial ────────────────────────

MESES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
}

def obtener_ediciones():
    for url in ["https://www.registroficial.gob.ec/registro-oficial/", "https://www.registroficial.gob.ec/"]:
        try:
            r = requests.get(url, headers=HEADERS_HTTP, timeout=20)
            if r.status_code == 200:
                html = r.text
                break
        except Exception:
            continue
    else:
        print("  No se pudo acceder al Registro Oficial.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    ediciones, vistos = [], set()

    for link in soup.find_all("a", href=True):
        texto = link.get_text(strip=True)
        href  = link["href"]

        m_num = re.search(r"(?:N[°º.]?\s*)?(\d{3,4})", texto)
        if not m_num or m_num.group(1) in vistos:
            continue

        m_fecha = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I)
        if not m_fecha:
            continue
        try:
            dia, mes, anio = int(m_fecha.group(1)), MESES.get(m_fecha.group(2).lower(), 0), int(m_fecha.group(3))
            if not mes or not (2020 <= anio <= 2030):
                continue
            fecha = date(anio, mes, dia)
        except Exception:
            continue

        numero = m_num.group(1)
        tipo   = "suplemento" if "suplemento" in texto.lower() else ("especial" if "especial" in texto.lower() else "ordinario")
        num_ro = f"RO-S N° {numero}" if tipo == "suplemento" else f"RO N° {numero}"
        url_c  = href if href.startswith("http") else f"https://www.registroficial.gob.ec{href}"

        ediciones.append({"numero": num_ro, "tipo": tipo, "fecha": str(fecha), "url": url_c, "url_pdf": None})
        vistos.add(numero)

    print(f"  {len(ediciones)} ediciones encontradas.")
    return ediciones

def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        r = requests.get(url_pdf, headers=HEADERS_HTTP, timeout=30)
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

# ── Clasificador con Google Gemini (GRATIS) ───────────────

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
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        d   = json.loads(raw)

        if d.get("jerarquia") not in JERARQUIAS:
            d["jerarquia"] = _map_jerarquia(d.get("jerarquia", "")) or "Otro"
        if d.get("vigencia") not in VIGENCIAS:
            d["vigencia"] = "Vigente"
        if d.get("tematica") not in TEMATICAS:
            d["tematica"] = "Otro"
        return d
    except Exception as e:
        print(f"    Gemini error: {e}")
        return None

def _map_jerarquia(t):
    if not t: return None
    t = t.lower()
    for k, v in [("ley orgánica","Ley Orgánica"),("ley organica","Ley Orgánica"),
                 ("ley ordinaria","Ley Ordinaria"),("decreto ejecutivo","Decreto Ejecutivo"),
                 ("decreto ley","Decreto Ley"),("reglamento","Reglamento"),
                 ("ordenanza","Ordenanza"),("resolución","Resolución"),("resolucion","Resolución"),
                 ("acuerdo ministerial","Acuerdo Ministerial"),("circular","Circular"),
                 ("instructivo","Instructivo"),("constitución","Constitución"),("constitucion","Constitución")]:
        if k in t: return v
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
        print(f"  [{ed['numero']}] Ya existe.")
        return 0

    print(f"  [{ed['numero']}] Procesando ({ed['fecha']})...")
    texto = None

    if ed.get("url_pdf"):
        texto = extraer_texto_pdf(ed["url_pdf"])

    if not texto and ed.get("url"):
        try:
            r    = requests.get(ed["url"], headers=HEADERS_HTTP, timeout=20)
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
        print(f"    Sin texto.")
        log("WARNING", f"Sin texto para {ed['numero']}")
        return 0

    segmentos = separar_normas(texto)
    print(f"    {len(segmentos)} normas detectadas")

    guardadas = 0
    for i, seg in enumerate(segmentos, 1):
        print(f"    Clasificando {i}/{len(segmentos)}...")
        c = clasificar(seg) or {"titulo": f"Norma {ed['numero']} seg.{i}", "jerarquia": "Otro", "vigencia": "Vigente", "tematica": "Otro", "sumario": seg[:300]}
        arts = extraer_arts(seg)

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
            "articulos":    arts or None,
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

# ── Main ──────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"\n{'='*50}\nLexEC Scraper — {inicio.strftime('%Y-%m-%d %H:%M')}\n{'='*50}\n")
    log("INFO", f"Iniciado — {inicio.strftime('%Y-%m-%d %H:%M')}")

    ediciones = obtener_ediciones()
    if not ediciones:
        log("INFO", "Sin ediciones nuevas")
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
