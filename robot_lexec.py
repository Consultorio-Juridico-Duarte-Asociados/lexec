#!/usr/bin/env python3
"""
LexEC Robot Multi-fuente v6
- Más páginas por fuente (historial completo)
- Nuevas fuentes: SRI, Cancillería, Finanzas, ARCOTEL, 
  Ministerio de Ambiente, Superintendencias, Presidencia MINKA
"""

import os, re, json, time, hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS_SB = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"
}
MESES = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05",
         "junio":"06","julio":"07","agosto":"08","septiembre":"09",
         "octubre":"10","noviembre":"11","diciembre":"12"}

# ── Supabase ───────────────────────────────────────────────────────────────────
def sb_get(table, params=""):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?{params}",
                     headers=HEADERS_SB, timeout=30)
    if r.status_code == 200: return r.json()
    print(f"  ⚠ GET {table}: {r.status_code} {r.text[:80]}")
    return []

def sb_insert(table, data):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                      headers=HEADERS_SB, data=json.dumps(data), timeout=30)
    return r.status_code in (200, 201)

def get_existentes():
    rows = sb_get("normas", "select=codigo_unico&limit=5000")
    return {r["codigo_unico"] for r in rows if r.get("codigo_unico")}

def insertar(norma, ex):
    cod = norma.get("codigo_unico","")
    if not cod or cod in ex: return False
    if sb_insert("normas", norma):
        ex.add(cod); return True
    return False

def log(fuente, cantidad, detalles):
    sb_insert("extracciones", {
        "fecha": datetime.now().isoformat(), "fuente": fuente,
        "cantidad": cantidad, "estado": "exitoso", "detalles": detalles,
    })

# ── Helpers ────────────────────────────────────────────────────────────────────
def limpiar_fecha(t):
    if not t: return datetime.now().strftime("%Y-%m-%d")
    t = t.lower().strip()
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", t)
    if m:
        mes = MESES.get(m.group(2))
        if mes: return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m2: return m2.group(0)
    m3 = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", t)
    if m3: return f"{m3.group(3)}-{m3.group(2).zfill(2)}-{m3.group(1).zfill(2)}"
    return datetime.now().strftime("%Y-%m-%d")

def limpiar_ro(t):
    if not t: return ""
    m = re.search(r"(?:RO|Registro\s+Oficial)[^\d]*(\d+)", t, re.IGNORECASE)
    if m:
        sup = bool(re.search(r"suplemento", t, re.IGNORECASE))
        return f"RO-S N° {m.group(1)}" if sup else f"RO N° {m.group(1)}"
    return ""

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS_WEB, timeout=25)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠ {url[:70]}: {e}")
        return None

def mk(cod, titulo, tipo, jerarquia, jnombre, fecha, fuente,
       url_fuente, url_pdf, resumen, numero_ro="", etiquetas=None):
    return {
        "codigo_unico": cod, "numero_ro": numero_ro,
        "titulo": titulo[:400], "tipo": tipo,
        "jerarquia": jerarquia, "jerarquia_nombre": jnombre,
        "fecha_publicacion": fecha, "fecha_extraccion": datetime.now().isoformat(),
        "registro_oficial": numero_ro, "fuente": fuente,
        "url_fuente": url_fuente, "url_pdf": url_pdf,
        "resumen": resumen[:600], "etiquetas": etiquetas or [],
        "estado": "vigente", "activo": True, "verificado": False,
    }

# ══════════════════════════════════════════════════════════════════════════════
# FUENTES EXISTENTES (ampliadas con más páginas)
# ══════════════════════════════════════════════════════════════════════════════

def scrape_presidencia(ex):
    print("📌 F1: Presidencia — Decretos Ejecutivos")
    total = 0
    base = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    for p in range(1, 15):  # hasta 15 páginas (antes: 6)
        url = base if p == 1 else f"{base}page/{p}/"
        soup = get_soup(url)
        if not soup: break
        nuevos = 0
        for fila in soup.find_all("tr"):
            cols = fila.find_all("td")
            if len(cols) < 3: continue
            num_raw, fecha_raw, asunto = (cols[i].get_text(strip=True) for i in range(3))
            link = fila.find("a", href=True)
            if not link or ".pdf" not in link["href"].lower(): continue
            num = re.sub(r"[^\d]", "", num_raw)
            if not num: continue
            cod = f"DE-{num}-{limpiar_fecha(fecha_raw)[:4]}"
            n = mk(cod, f"Decreto Ejecutivo No. {num}", "Decreto Ejecutivo",
                   4, "Decreto Ejecutivo", limpiar_fecha(fecha_raw),
                   "Presidencia de la República", url, link["href"],
                   asunto[:600], limpiar_ro(asunto), ["presidencia","decreto-ejecutivo"])
            if insertar(n, ex):
                print(f"  ✅ DE-{num}"); nuevos += 1; total += 1
        if nuevos == 0 and p > 2: break
        time.sleep(1)
    return total

def scrape_asamblea(ex):
    print("\n📌 F2: Asamblea Nacional — Leyes (todas las páginas)")
    total = 0
    for p in range(0, 20):  # hasta 20 páginas (antes: 1)
        url = f"https://www.asambleanacional.gob.ec/es/leyes-aprobadas?page={p}"
        soup = get_soup(url)
        if not soup: break
        nuevos = 0
        for row in soup.find_all("tr"):
            pdf = row.find("a", href=lambda h: h and ".pdf" in h.lower())
            if not pdf: continue
            cells = row.find_all("td")
            titulo = " ".join(c.get_text(strip=True) for c in cells).strip()[:300]
            if not titulo or len(titulo) < 15: continue
            href = pdf["href"]
            if not href.startswith("http"):
                href = "https://www.asambleanacional.gob.ec" + href
            num_m = re.search(r"^(\d+)\s", titulo)
            num = num_m.group(1) if num_m else hashlib.md5(titulo.encode()).hexdigest()[:6]
            fecha_m = re.search(r"\d{2}-\d{2}-\d{4}", titulo)
            fecha = limpiar_fecha(fecha_m.group(0) if fecha_m else "")
            ro = limpiar_ro(titulo)
            tipo = "Ley Orgánica" if "orgánica" in titulo.lower() else "Ley Ordinaria"
            cod = f"AN-LEY-{num}-{fecha[:4]}"
            n = mk(cod, titulo, tipo, 3, tipo, fecha,
                   "Asamblea Nacional",
                   "https://www.asambleanacional.gob.ec/es/leyes-aprobadas",
                   href, titulo, ro, ["asamblea-nacional","ley"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:70]}"); nuevos += 1; total += 1
        if nuevos == 0 and p > 0: break
        time.sleep(1.5)
    return total

def scrape_trabajo(ex):
    print("\n📌 F3: Ministerio del Trabajo")
    total = 0
    # Scrape multiple pages
    for p in range(1, 10):
        url = "https://www.trabajo.gob.ec/acuerdos-ministeriales/" if p == 1 else \
              f"https://www.trabajo.gob.ec/acuerdos-ministeriales/page/{p}/"
        soup = get_soup(url)
        if not soup: break
        nuevos = 0
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            num_m = re.search(r"MDT-(\d{4})-(\d+)", titulo)
            if not num_m: continue
            año, num = num_m.group(1), num_m.group(2)
            href = link["href"]
            if not href.startswith("http"): href = "https://www.trabajo.gob.ec" + href
            fecha_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", titulo.lower())
            fecha = limpiar_fecha(fecha_m.group(0) if fecha_m else f"01 de enero de {año}")
            cod = f"MDT-AM-{año}-{num}"
            n = mk(cod, titulo[:300], "Acuerdo Ministerial", 5,
                   "Acuerdo Ministerial", fecha, "Ministerio del Trabajo",
                   "https://www.trabajo.gob.ec/acuerdos-ministeriales/",
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["trabajo","acuerdo-ministerial",f"mdt-{año}"])
            if insertar(n, ex):
                print(f"  ✅ MDT-{año}-{num}"); nuevos += 1; total += 1
        if nuevos == 0 and p > 1: break
        time.sleep(1)
    return total

def scrape_sercop(ex):
    print("\n📌 F4: SERCOP")
    total = 0
    for url in [
        "https://portal.compraspublicas.gob.ec/sercop/normativa/resoluciones/",
        "https://portal.compraspublicas.gob.ec/sercop/normativa/",
        "https://portal.compraspublicas.gob.ec/sercop/normativa/resoluciones/?page=2",
        "https://portal.compraspublicas.gob.ec/sercop/normativa/resoluciones/?page=3",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            if not re.search(r"\d{3,}", titulo): continue
            if not any(k in titulo.lower() for k in ["resoluc","reglamento","acuerdo","normativa"]): continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://portal.compraspublicas.gob.ec" + href
            num_m = re.search(r"(?:RE|RESOLUCION|Resolucion)[^\d]*(\d+)", titulo, re.IGNORECASE)
            if not num_m: num_m = re.search(r"\d{3,}", titulo)
            num = num_m.group(0) if num_m else ""
            cod = f"SERCOP-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = mk(cod, titulo[:300], "Resolución", 5, "Resolución SERCOP",
                   datetime.now().strftime("%Y-%m-%d"), "SERCOP", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["sercop","contratacion-publica"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_salud(ex):
    print("\n📌 F5: Ministerio de Salud")
    total = 0
    soup = get_soup("https://www.salud.gob.ec/acuerdos-ministeriales/")
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if ".pdf" not in href.lower(): continue
        p = link.find_parent(["li","tr","div","td","article","p"])
        titulo = p.get_text(separator=" ", strip=True)[:200] if p else link.get_text(strip=True)
        titulo = re.sub(r"\s+", " ", titulo).strip()
        if not re.search(r"\d{3,}", titulo): continue
        if not href.startswith("http"): href = "https://www.salud.gob.ec" + href
        num_m = re.search(r"AM[_\-\s]*(\d+)|(\d{4})[_\-](\d{3,})", titulo)
        num = num_m.group(0).replace(" ","") if num_m else hashlib.md5(href.encode()).hexdigest()[:8]
        cod = f"MSP-AM-{re.sub(r'[^a-z0-9]','-',num.lower())}"
        n = mk(cod, titulo[:300], "Acuerdo Ministerial", 5,
               "Acuerdo Ministerial de Salud", datetime.now().strftime("%Y-%m-%d"),
               "Ministerio de Salud Pública",
               "https://www.salud.gob.ec/acuerdos-ministeriales/",
               href, titulo[:600], "", ["salud","acuerdo-ministerial"])
        if insertar(n, ex):
            print(f"  ✅ {titulo[:60]}"); total += 1
    return total

def scrape_judicatura(ex):
    print("\n📌 F6: Función Judicial")
    total = 0
    for url in [
        "https://www.funcionjudicial.gob.ec/normativa/resoluciones",
        "https://www.funcionjudicial.gob.ec/index.php/normativa",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" not in href.lower(): continue
            parent = link.find_parent(["tr","li","div","article","td"])
            titulo = parent.get_text(separator=" ", strip=True)[:200] if parent else link.get_text(strip=True)
            titulo = re.sub(r"\s+", " ", titulo).strip()
            if not titulo or len(titulo) < 10: continue
            if re.match(r"^(PAC|Informe|Memoria)\s+\d{4}", titulo): continue
            if titulo.lower() in ["ver documento","descargar","pdf","ver","download"]: continue
            if not re.search(r"\d{3,}", titulo): continue
            if not href.startswith("http"):
                href = "https://www.funcionjudicial.gob.ec" + href
            num_m = re.search(r"\d{3,4}-\d{4}", titulo)
            num = num_m.group(0) if num_m else hashlib.md5(href.encode()).hexdigest()[:8]
            cod = f"FJ-RES-{num}"
            n = mk(cod, titulo[:300], "Resolución", 5,
                   "Resolución del Consejo de la Judicatura",
                   datetime.now().strftime("%Y-%m-%d"),
                   "Consejo de la Judicatura", url, href,
                   titulo[:600], "", ["judicatura","resolucion"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        if total > 0: break
    return total

# ══════════════════════════════════════════════════════════════════════════════
# NUEVAS FUENTES
# ══════════════════════════════════════════════════════════════════════════════

def scrape_sri(ex):
    print("\n📌 F7: SRI — Resoluciones Tributarias")
    total = 0
    urls = [
        "https://www.sri.gob.ec/web/guest/resoluciones",
        "https://www.sri.gob.ec/web/guest/resoluciones-generales",
        "https://www.sri.gob.ec/resoluciones",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            num_m = re.search(r"NAC-DGERCGC\d+-\d+|NAC-\w+-\d+|NACC-\d+", titulo, re.IGNORECASE)
            if not num_m: continue
            href = link["href"]
            if not href.startswith("http"): href = "https://www.sri.gob.ec" + href
            num = num_m.group(0)
            cod = f"SRI-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            fecha_m = re.search(r"\d{4}", titulo)
            fecha = f"{fecha_m.group(0)}-01-01" if fecha_m else datetime.now().strftime("%Y-%m-%d")
            n = mk(cod, titulo[:300], "Resolución Tributaria", 5,
                   "Resolución SRI", fecha, "Servicio de Rentas Internas",
                   href, href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["sri","tributario"])
            if insertar(n, ex):
                print(f"  ✅ {num}"); total += 1
        if total > 0: break
        time.sleep(1)
    return total

def scrape_cancilleria(ex):
    print("\n📌 F8: Cancillería — Tratados Internacionales")
    total = 0
    urls = [
        "https://www.cancilleria.gob.ec/tratados-internacionales/",
        "https://www.cancilleria.gob.ec/normativa/",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 15: continue
            if not any(k in titulo.lower() for k in
                ["tratado","convenio","acuerdo","protocolo","convención","carta"]): continue
            href = link["href"]
            if not href.startswith("http"): href = "https://www.cancilleria.gob.ec" + href
            cod = f"CANC-{hashlib.md5(titulo.encode()).hexdigest()[:10]}"
            n = mk(cod, titulo[:300], "Tratado Internacional", 2,
                   "Tratado Internacional", datetime.now().strftime("%Y-%m-%d"),
                   "Cancillería del Ecuador", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["cancilleria","tratado","internacional"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_finanzas(ex):
    print("\n📌 F9: Ministerio de Finanzas")
    total = 0
    urls = [
        "https://www.finanzas.gob.ec/acuerdos-ministeriales/",
        "https://www.finanzas.gob.ec/normativa/",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            href = link["href"]
            if not href.startswith("http"): href = "https://www.finanzas.gob.ec" + href
            num_m = re.search(r"AM-\d+|MF-\d+|\d{4}-\d{3,}", titulo)
            if not num_m and ".pdf" not in href.lower(): continue
            num = num_m.group(0) if num_m else hashlib.md5(titulo.encode()).hexdigest()[:8]
            cod = f"MEF-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = mk(cod, titulo[:300], "Acuerdo Ministerial", 5,
                   "Acuerdo Ministerial de Finanzas",
                   datetime.now().strftime("%Y-%m-%d"),
                   "Ministerio de Finanzas", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["finanzas","acuerdo-ministerial"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_ambiente(ex):
    print("\n📌 F10: Ministerio de Ambiente")
    total = 0
    for url in [
        "https://www.ambiente.gob.ec/acuerdos-ministeriales/",
        "https://www.ambiente.gob.ec/normativa/",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            href = link["href"]
            if not href.startswith("http"): href = "https://www.ambiente.gob.ec" + href
            num_m = re.search(r"MAATE?-\w+-\d+|AM-\d+|\d{4}-\d{3,}", titulo)
            if not num_m and ".pdf" not in href.lower(): continue
            num = num_m.group(0) if num_m else hashlib.md5(titulo.encode()).hexdigest()[:8]
            cod = f"MAATE-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = mk(cod, titulo[:300], "Acuerdo Ministerial", 5,
                   "Acuerdo Ministerial Ambiental",
                   datetime.now().strftime("%Y-%m-%d"),
                   "Ministerio de Ambiente", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["ambiente","acuerdo-ministerial"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_supercias(ex):
    print("\n📌 F11: Superintendencia de Compañías")
    total = 0
    urls = [
        "https://www.supercias.gob.ec/portalscvs/",
        "https://www.supercias.gob.ec/bd_supercias/descargas/ss/resoluciones/",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            if not any(k in titulo.lower() for k in ["resoluc","normativa","reglamento","circular"]): continue
            href = link["href"]
            if not href.startswith("http"): href = "https://www.supercias.gob.ec" + href
            num_m = re.search(r"SC-\w+-\d+|Q-\d+|\d{4}-\d{3,}", titulo)
            num = num_m.group(0) if num_m else hashlib.md5(titulo.encode()).hexdigest()[:8]
            cod = f"SCVS-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = mk(cod, titulo[:300], "Resolución", 5,
                   "Resolución Superintendencia de Compañías",
                   datetime.now().strftime("%Y-%m-%d"),
                   "Superintendencia de Compañías", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["supercias","mercado-valores"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_minka(ex):
    """MINKA — Plataforma oficial de decretos de la Presidencia"""
    print("\n📌 F12: MINKA — Presidencia (Decretos y Reglamentos)")
    total = 0
    urls = [
        "https://minka.presidencia.gob.ec/portal/public/decretos",
        "https://minka.presidencia.gob.ec/portal/public/resoluciones",
        "https://minka.presidencia.gob.ec/portal/public/reglamentos",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            href = link["href"]
            if not href.startswith("http"): href = "https://minka.presidencia.gob.ec" + href
            num_m = re.search(r"No?\.\s*(\d+)|decreto\s+(\d+)", titulo, re.IGNORECASE)
            num = num_m.group(1) or num_m.group(2) if num_m else hashlib.md5(titulo.encode()).hexdigest()[:8]
            tipo = "Decreto Ejecutivo" if "decreto" in url else \
                   "Reglamento" if "reglamento" in url else "Resolución Ejecutiva"
            cod = f"MINKA-{tipo[:2].upper()}-{num}"
            n = mk(cod, titulo[:300], tipo, 4, tipo,
                   datetime.now().strftime("%Y-%m-%d"),
                   "MINKA — Plataforma Oficial Presidencia", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], "", ["presidencia","minka",tipo.lower().replace(" ","-")])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

def scrape_registro_oficial(ex):
    """Registro Oficial — Últimas publicaciones"""
    print("\n📌 F13: Registro Oficial")
    total = 0
    urls = [
        "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/suplementos",
        "https://www.registroficial.gob.ec/index.php/registro-oficial-web/publicaciones/registro-oficial",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            if not any(k in titulo.lower() for k in
                ["ley","código","decreto","reglamento","resolución","acuerdo","registro oficial"]): continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://www.registroficial.gob.ec" + href
            cod = f"RO-{hashlib.md5((titulo+href).encode()).hexdigest()[:10]}"
            n = mk(cod, titulo[:300], "Norma del Registro Oficial", 5,
                   "Norma", datetime.now().strftime("%Y-%m-%d"),
                   "Registro Oficial", href,
                   href if ".pdf" in href.lower() else "",
                   titulo[:600], limpiar_ro(titulo), ["registro-oficial"])
            if insertar(n, ex):
                print(f"  ✅ {titulo[:60]}"); total += 1
        time.sleep(1)
    return total

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=" * 65)
    print("🤖 LexEC Robot Multi-fuente v6")
    print(f"   13 fuentes | historial completo")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    print("\n🔑 Conectando a Supabase...")
    ex = get_existentes()
    print(f"📚 Normas existentes: {len(ex)}\n")

    fuentes = [
        ("Presidencia",          scrape_presidencia),
        ("Asamblea Nacional",    scrape_asamblea),
        ("Trabajo",              scrape_trabajo),
        ("SERCOP",               scrape_sercop),
        ("Salud",                scrape_salud),
        ("Judicatura",           scrape_judicatura),
        ("SRI",                  scrape_sri),
        ("Cancillería",          scrape_cancilleria),
        ("Finanzas",             scrape_finanzas),
        ("Ambiente",             scrape_ambiente),
        ("Supercias",            scrape_supercias),
        ("MINKA",                scrape_minka),
        ("Registro Oficial",     scrape_registro_oficial),
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
    print("📊 RESUMEN FINAL:")
    for nombre, n in resultados.items():
        print(f"  {'✅' if n > 0 else '➖'} {nombre}: {n} normas")
    print(f"\n🎉 TOTAL: {total} normas nuevas — {dur}s")
    print("=" * 65)
    log("GitHub Actions v6", total,
        f"v6 — {total} normas. " +
        " | ".join(f"{k}:{v}" for k,v in resultados.items() if v > 0))

if __name__ == "__main__":
    main()
