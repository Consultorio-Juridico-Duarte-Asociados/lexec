#!/usr/bin/env python3
"""
LexEC Robot Multi-fuente — columnas exactas de Supabase
Basado en robot_presidencia.py que ya funciona.
"""

import os, re, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from supabase import create_client

# ── Configuración ──────────────────────────────────────────────────────────────
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}

MESES = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05",
         "junio":"06","julio":"07","agosto":"08","septiembre":"09",
         "octubre":"10","noviembre":"11","diciembre":"12"}

# ── Helpers ────────────────────────────────────────────────────────────────────
def limpiar_fecha(texto):
    if not texto: return datetime.now().strftime("%Y-%m-%d")
    t = texto.lower().strip()
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})", t)
    if m:
        mes = MESES.get(m.group(2))
        if mes: return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m2: return m2.group(0)
    m3 = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", t)
    if m3: return f"{m3.group(3)}-{m3.group(2).zfill(2)}-{m3.group(1).zfill(2)}"
    return datetime.now().strftime("%Y-%m-%d")

def limpiar_numero_ro(texto):
    if not texto: return None
    m = re.search(r"(?:RO|Registro\s+Oficial)[^\d]*(\d+)", texto, re.IGNORECASE)
    if m:
        es_sup = bool(re.search(r"suplemento", texto, re.IGNORECASE))
        return f"RO-S N° {m.group(1)}" if es_sup else f"RO N° {m.group(1)}"
    return None

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠ {url}: {e}")
        return None

def insertar(data):
    """Inserta usando exactamente las mismas columnas que robot_presidencia.py"""
    try:
        supabase.table("normas").insert(data).execute()
        return True
    except Exception as e:
        err = str(e)
        if "duplicate" in err.lower() or "23505" in err:
            return False  # ya existe, ok
        print(f"  ⚠ Insert error: {e}")
        return False

def log(fuente, cantidad, detalles):
    try:
        supabase.table("extracciones").insert({
            "fecha":    datetime.now().isoformat(),
            "fuente":   fuente,
            "cantidad": cantidad,
            "estado":   "exitoso",
            "detalles": detalles,
        }).execute()
    except: pass

# ── FUENTE 1: Presidencia — Decretos Ejecutivos ────────────────────────────────
def scrape_presidencia():
    print("📌 FUENTE 1: Presidencia (Decretos Ejecutivos)")
    total = 0
    base_url = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    for p in range(1, 5):
        url = base_url if p == 1 else f"{base_url}page/{p}/"
        soup = get_soup(url)
        if not soup: break
        nuevos = 0
        for fila in soup.find_all("tr"):
            cols = fila.find_all("td")
            if len(cols) < 3: continue
            num_raw   = cols[0].get_text(strip=True)
            fecha_raw = cols[1].get_text(strip=True)
            asunto    = cols[2].get_text(strip=True)
            link = fila.find("a", href=True)
            if not link or ".pdf" not in link["href"].lower(): continue

            num = re.sub(r"[^\d]", "", num_raw)
            titulo = f"Decreto Ejecutivo No. {num}" if num else f"Decreto: {asunto[:80]}"
            fecha  = limpiar_fecha(fecha_raw)
            n_ro   = limpiar_numero_ro(asunto)

            data = {
                "titulo":       titulo,
                "numero_norma": num,
                "numero_ro":    n_ro,
                "jerarquia":    "Decreto Ejecutivo",
                "vigencia":     "Vigente",
                "fecha_pub":    fecha,
                "url_pdf":      link["href"],
                "sumario":      asunto[:500],
                "origen":       "Presidencia de la República",
                "metodo_ocr":   "scraper-presidencia",
            }
            if insertar(data):
                print(f"  ✅ {titulo} | {fecha}")
                nuevos += 1; total += 1
        if nuevos == 0 and p > 1: break
        time.sleep(1.5)
    return total

# ── FUENTE 2: Asamblea Nacional ────────────────────────────────────────────────
def scrape_asamblea():
    print("\n📌 FUENTE 2: Asamblea Nacional")
    total = 0
    for p in range(0, 4):
        url = f"https://www.asambleanacional.gob.ec/es/leyes-aprobadas?page={p}"
        soup = get_soup(url)
        if not soup: continue
        nuevos = 0
        for row in soup.find_all(["tr", "article", "li"]):
            link = row.find("a", href=True)
            if not link: continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 15: continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://www.asambleanacional.gob.ec" + href

            # Fecha
            fecha_txt = ""
            for el in row.find_all(["td","span","div","p"]):
                t = el.get_text(strip=True)
                if re.search(r"\d{4}", t) and len(t) < 50:
                    fecha_txt = t; break
            fecha = limpiar_fecha(fecha_txt)

            # PDF
            pdf_a = row.find("a", href=lambda h: h and ".pdf" in h.lower())
            url_pdf = pdf_a["href"] if pdf_a else href
            if url_pdf and not url_pdf.startswith("http"):
                url_pdf = "https://www.asambleanacional.gob.ec" + url_pdf

            tipo = "Ley Orgánica" if "orgánica" in titulo.lower() else "Ley Ordinaria"

            data = {
                "titulo":       titulo[:300],
                "numero_norma": "",
                "numero_ro":    None,
                "jerarquia":    tipo,
                "vigencia":     "Vigente",
                "fecha_pub":    fecha,
                "url_pdf":      url_pdf,
                "sumario":      titulo[:500],
                "origen":       "Asamblea Nacional",
                "metodo_ocr":   "scraper-asamblea",
            }
            if insertar(data):
                print(f"  ✅ {titulo[:70]}")
                nuevos += 1; total += 1
        if nuevos == 0 and p > 0: break
        time.sleep(2)
    return total

# ── FUENTE 3: SERCOP ───────────────────────────────────────────────────────────
def scrape_sercop():
    print("\n📌 FUENTE 3: SERCOP")
    total = 0
    for url in [
        "https://portal.compraspublicas.gob.ec/sercop/normativa/resoluciones/",
        "https://portal.compraspublicas.gob.ec/sercop/normativa/",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            if not any(k in titulo.lower() for k in ["resoluc","normativa","reglamento","acuerdo"]): continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://portal.compraspublicas.gob.ec" + href
            num_m = re.search(r"RE-\d{4}-\d+|SERCOP-\d+|\d{3,4}", titulo)
            num = num_m.group(0) if num_m else ""
            data = {
                "titulo":       titulo[:300],
                "numero_norma": num,
                "numero_ro":    None,
                "jerarquia":    "Resolución",
                "vigencia":     "Vigente",
                "fecha_pub":    datetime.now().strftime("%Y-%m-%d"),
                "url_pdf":      href if ".pdf" in href.lower() else "",
                "sumario":      titulo[:500],
                "origen":       "SERCOP",
                "metodo_ocr":   "scraper-sercop",
            }
            if insertar(data):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        time.sleep(1)
    return total

# ── FUENTE 4: Ministerio del Trabajo ──────────────────────────────────────────
def scrape_trabajo():
    print("\n📌 FUENTE 4: Ministerio del Trabajo")
    total = 0
    soup = get_soup("https://www.trabajo.gob.ec/acuerdos-ministeriales/")
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 10: continue
        if not any(k in titulo.lower() for k in ["acuerdo","ministerial","resoluc"]): continue
        href = link["href"]
        if not href.startswith("http"): href = "https://www.trabajo.gob.ec" + href
        num_m = re.search(r"MDT-\d{4}-\d+|\d{3,4}", titulo)
        num = num_m.group(0) if num_m else ""
        data = {
            "titulo":       titulo[:300],
            "numero_norma": num,
            "numero_ro":    None,
            "jerarquia":    "Acuerdo Ministerial",
            "vigencia":     "Vigente",
            "fecha_pub":    datetime.now().strftime("%Y-%m-%d"),
            "url_pdf":      href if ".pdf" in href.lower() else "",
            "sumario":      titulo[:500],
            "origen":       "Ministerio del Trabajo",
            "metodo_ocr":   "scraper-trabajo",
        }
        if insertar(data):
            print(f"  ✅ {titulo[:70]}")
            total += 1
    return total

# ── FUENTE 5: Ministerio de Salud ─────────────────────────────────────────────
def scrape_salud():
    print("\n📌 FUENTE 5: Ministerio de Salud")
    total = 0
    soup = get_soup("https://www.salud.gob.ec/acuerdos-ministeriales/")
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 10: continue
        href = link["href"]
        if not href.startswith("http"): href = "https://www.salud.gob.ec" + href
        num_m = re.search(r"AM\s*\d+|\d{4}-\d{3,}", titulo)
        num = num_m.group(0) if num_m else ""
        data = {
            "titulo":       titulo[:300],
            "numero_norma": num,
            "numero_ro":    None,
            "jerarquia":    "Acuerdo Ministerial",
            "vigencia":     "Vigente",
            "fecha_pub":    datetime.now().strftime("%Y-%m-%d"),
            "url_pdf":      href if ".pdf" in href.lower() else "",
            "sumario":      titulo[:500],
            "origen":       "Ministerio de Salud Pública",
            "metodo_ocr":   "scraper-salud",
        }
        if insertar(data):
            print(f"  ✅ {titulo[:70]}")
            total += 1
    return total

# ── FUENTE 6: Función Judicial ─────────────────────────────────────────────────
def scrape_funcion_judicial():
    print("\n📌 FUENTE 6: Función Judicial")
    total = 0
    # Try multiple URLs
    for url in [
        "https://www.funcionjudicial.gob.ec/normativa/resoluciones",
        "https://www.funcionjudicial.gob.ec/index.php/normativa",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" not in href.lower(): continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 8: continue
            if not href.startswith("http"):
                href = "https://www.funcionjudicial.gob.ec" + href
            num_m = re.search(r"\d{3,4}-\d{4}", titulo)
            num = num_m.group(0) if num_m else ""
            data = {
                "titulo":       titulo[:300],
                "numero_norma": num,
                "numero_ro":    None,
                "jerarquia":    "Resolución",
                "vigencia":     "Vigente",
                "fecha_pub":    datetime.now().strftime("%Y-%m-%d"),
                "url_pdf":      href,
                "sumario":      titulo[:500],
                "origen":       "Consejo de la Judicatura",
                "metodo_ocr":   "scraper-judicatura",
            }
            if insertar(data):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        if total > 0: break
    return total

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=" * 65)
    print("🤖 LexEC Robot Multi-fuente v2")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    resultados = {}
    fuentes = [
        ("Presidencia",       scrape_presidencia),
        ("Asamblea Nacional", scrape_asamblea),
        ("SERCOP",            scrape_sercop),
        ("Trabajo",           scrape_trabajo),
        ("Salud",             scrape_salud),
        ("Judicatura",        scrape_funcion_judicial),
    ]

    for nombre, fn in fuentes:
        try:
            resultados[nombre] = fn()
        except Exception as e:
            print(f"  ❌ Error en {nombre}: {e}")
            resultados[nombre] = 0

    total = sum(resultados.values())
    dur   = round(time.time() - t0, 1)

    print("\n" + "=" * 65)
    print("📊 RESUMEN:")
    for nombre, n in resultados.items():
        print(f"  {'✅' if n > 0 else '➖'} {nombre}: {n} normas nuevas")
    print(f"\n🎉 TOTAL: {total} normas — {dur}s")
    print("=" * 65)

    resumen = " | ".join(f"{k}: {v}" for k,v in resultados.items() if v > 0)
    log("GitHub Actions", total, f"{total} normas. {resumen or 'Sin nuevas'}")

if __name__ == "__main__":
    main()
