#!/usr/bin/env python3
"""
LexEC Robot Multi-fuente v3 — filtros estrictos para normas reales
"""

import os, re, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"}

MESES = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05",
         "junio":"06","julio":"07","agosto":"08","septiembre":"09",
         "octubre":"10","noviembre":"11","diciembre":"12"}

# Palabras que indican que ES una norma legal real
KEYWORDS_NORMA = [
    "ley ", "código ", "decreto", "resolución", "resolucin", "acuerdo ministerial",
    "reglamento", "ordenanza", "estatuto", "norma", "instructivo", "circular",
    "registro oficial", "suplemento", "reforma", "orgánica", "ordinaria",
    "expedir", "derogar", "modificar", "reformar", "aprobar"
]

def es_norma_real(titulo):
    """Filtra estrictamente — solo títulos que parezcan normas legales."""
    if not titulo or len(titulo) < 15: return False
    t = titulo.lower()
    # Excluir links de navegación/menú
    excluir = [
        "click aquí", "ver documento", "ver más", "leer más", "inicio",
        "contacto", "transparencia", "biblioteca", "servicios", "programas",
        "quipux", "trámites", "compras públicas", "directorio", "secretarías",
        "ministerios", "vicepresidencia", "presidencia de la", "sin categoría",
        "pleno -", "consejo de administración", "secretaría técnica legislativa",
        "documentos oficiales", "archivo -", "histórico de actas", "consulta de",
        "gestión del", "sistema de", "trámite de", "resoluciones de la presidencia",
        "presupuesto general", "tratados e", "resoluciones del pleno",
        "votaciones", "solicitudes de", "informes de", "participación ciudadana",
        "plataforma participa", "grupos inter", "organismos inter", "noticias",
        "coordinación de", "pac 202", "informe de labores", "firma electrónica",
        "registro de títulos", "constitución de compañías", "info digital",
        "gobierno por resultado", "sistema nacional", "portal trámites",
        "contacto ciudadano", "el ministerio", "el presidente", "la presidencia",
        "el vicepresidente", "palacio de gobierno", "agricultura y", "acuacultura",
        "comercio exterior", "cultura y", "defensa nacional", "desarrollo urbano",
        "electricidad y", "economía y", "hidrocarburos", "inclusión económica",
        "industrias y", "relaciones exteriores", "telecomunicaciones y",
        "transporte y", "mujer y", "salud pública", "educación superior",
        "gestión de riesgos", "código deontológico", "ley orgánica de comunicación",
        "administración", "gubernamentales", "acuerdos ministeriales 202",
    ]
    for ex in excluir:
        if ex in t: return False
    # Debe contener al menos una palabra clave de norma
    return any(kw in t for kw in KEYWORDS_NORMA)

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
    try:
        supabase.table("normas").insert(data).execute()
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "23505" in str(e): return False
        print(f"  ⚠ {e}")
        return False

def log(fuente, cantidad, detalles):
    try:
        supabase.table("extracciones").insert({
            "fecha": datetime.now().isoformat(),
            "fuente": fuente, "cantidad": cantidad,
            "estado": "exitoso", "detalles": detalles,
        }).execute()
    except: pass

# ── FUENTE 1: Presidencia ──────────────────────────────────────────────────────
def scrape_presidencia():
    print("📌 FUENTE 1: Presidencia")
    total = 0
    # Probar múltiples URLs posibles
    urls = [
        "https://www.presidencia.gob.ec/decretos-ejecutivos/",
        "https://www.presidencia.gob.ec/category/decretos/",
        "https://www.presidencia.gob.ec/normativa/",
    ]
    for base_url in urls:
        for p in range(1, 4):
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
                data = {
                    "titulo": titulo, "numero_norma": num,
                    "numero_ro": limpiar_numero_ro(asunto),
                    "jerarquia": "Decreto Ejecutivo", "vigencia": "Vigente",
                    "fecha_pub": limpiar_fecha(fecha_raw),
                    "url_pdf": link["href"], "sumario": asunto[:500],
                    "origen": "Presidencia de la República",
                    "metodo_ocr": "scraper-presidencia",
                }
                if insertar(data):
                    print(f"  ✅ {titulo}")
                    nuevos += 1; total += 1
            if nuevos > 0: break  # URL funcionó
            time.sleep(1)
        if total > 0: break
    return total

# ── FUENTE 2: Asamblea Nacional — SOLO leyes reales ───────────────────────────
def scrape_asamblea():
    print("\n📌 FUENTE 2: Asamblea Nacional")
    total = 0
    # URL específica de leyes aprobadas
    url = "https://www.asambleanacional.gob.ec/es/leyes-aprobadas"
    soup = get_soup(url)
    if not soup: return 0

    # Buscar la tabla o lista de leyes específicamente
    # La página tiene una tabla con las leyes
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2: continue

        # Buscar link a PDF en la fila
        pdf_link = row.find("a", href=lambda h: h and ".pdf" in h.lower())
        if not pdf_link: continue

        titulo = " ".join(c.get_text(strip=True) for c in cells if c.get_text(strip=True))
        titulo = titulo[:300]
        if not es_norma_real(titulo) and not pdf_link: continue

        href = pdf_link["href"]
        if not href.startswith("http"):
            href = "https://www.asambleanacional.gob.ec" + href

        # Extraer fecha de la fila
        fecha_txt = ""
        for cell in cells:
            t = cell.get_text(strip=True)
            if re.search(r"\d{4}", t) and len(t) < 30:
                fecha_txt = t; break

        tipo = "Ley Orgánica" if "orgánica" in titulo.lower() else "Ley Ordinaria"
        data = {
            "titulo": titulo, "numero_norma": "",
            "numero_ro": limpiar_numero_ro(titulo),
            "jerarquia": tipo, "vigencia": "Vigente",
            "fecha_pub": limpiar_fecha(fecha_txt),
            "url_pdf": href, "sumario": titulo[:500],
            "origen": "Asamblea Nacional",
            "metodo_ocr": "scraper-asamblea",
        }
        if insertar(data):
            print(f"  ✅ {titulo[:80]}")
            total += 1
    return total

# ── FUENTE 3: SERCOP — solo resoluciones con número ───────────────────────────
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
            # Solo si tiene número de resolución
            if not re.search(r"\d{3,}", titulo): continue
            if not any(k in titulo.lower() for k in ["resoluc","reglamento","acuerdo","normativa"]): continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://portal.compraspublicas.gob.ec" + href
            num_m = re.search(r"RE-\d{4}-\d+|\d{3,4}", titulo)
            data = {
                "titulo": titulo[:300], "numero_norma": num_m.group(0) if num_m else "",
                "numero_ro": None, "jerarquia": "Resolución", "vigencia": "Vigente",
                "fecha_pub": datetime.now().strftime("%Y-%m-%d"),
                "url_pdf": href if ".pdf" in href.lower() else "",
                "sumario": titulo[:500], "origen": "SERCOP",
                "metodo_ocr": "scraper-sercop",
            }
            if insertar(data):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        time.sleep(1)
    return total

# ── FUENTE 4: Ministerio del Trabajo — solo con número MDT ────────────────────
def scrape_trabajo():
    print("\n📌 FUENTE 4: Ministerio del Trabajo")
    total = 0
    soup = get_soup("https://www.trabajo.gob.ec/acuerdos-ministeriales/")
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 15: continue
        # Solo acuerdos con número MDT
        if not re.search(r"MDT-\d{4}-\d+", titulo): continue
        href = link["href"]
        if not href.startswith("http"): href = "https://www.trabajo.gob.ec" + href
        num_m = re.search(r"MDT-\d{4}-\d+", titulo)
        # Extraer fecha del título
        fecha_m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", titulo.lower())
        fecha = limpiar_fecha(fecha_m.group(0) if fecha_m else "")
        data = {
            "titulo": titulo[:300], "numero_norma": num_m.group(0) if num_m else "",
            "numero_ro": None, "jerarquia": "Acuerdo Ministerial", "vigencia": "Vigente",
            "fecha_pub": fecha,
            "url_pdf": href if ".pdf" in href.lower() else "",
            "sumario": titulo[:500], "origen": "Ministerio del Trabajo",
            "metodo_ocr": "scraper-trabajo",
        }
        if insertar(data):
            print(f"  ✅ {titulo[:80]}")
            total += 1
    return total

# ── FUENTE 5: Ministerio de Salud — solo PDFs de acuerdos ─────────────────────
def scrape_salud():
    print("\n📌 FUENTE 5: Ministerio de Salud")
    total = 0
    urls = [
        "https://www.salud.gob.ec/acuerdos-ministeriales/",
        "https://www.salud.gob.ec/acuerdos-ministeriales-2024/",
        "https://www.salud.gob.ec/acuerdos-ministeriales-2025/",
    ]
    for url in urls:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            titulo = link.get_text(strip=True)
            # Solo links que sean PDFs o tengan número de acuerdo
            if not href.lower().endswith(".pdf") and not re.search(r"AM\s*\d+|\d{4}-\d{3,}|acuerdo.*\d{3,}", titulo.lower()): continue
            if not titulo or len(titulo) < 10: continue
            if not href.startswith("http"): href = "https://www.salud.gob.ec" + href
            # Verificar que parece un acuerdo real
            if not re.search(r"\d{3,}", titulo) and ".pdf" not in href.lower(): continue
            num_m = re.search(r"AM\s*\d+|\d{4}-\d{3,}", titulo)
            data = {
                "titulo": titulo[:300], "numero_norma": num_m.group(0) if num_m else "",
                "numero_ro": None, "jerarquia": "Acuerdo Ministerial", "vigencia": "Vigente",
                "fecha_pub": datetime.now().strftime("%Y-%m-%d"),
                "url_pdf": href if ".pdf" in href.lower() else "",
                "sumario": titulo[:500], "origen": "Ministerio de Salud Pública",
                "metodo_ocr": "scraper-salud",
            }
            if insertar(data):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        time.sleep(1)
    return total

# ── FUENTE 6: Función Judicial — solo PDFs reales ─────────────────────────────
def scrape_funcion_judicial():
    print("\n📌 FUENTE 6: Función Judicial")
    total = 0
    for url in [
        "https://www.funcionjudicial.gob.ec/normativa/resoluciones",
        "https://www.funcionjudicial.gob.ec/index.php/normativa",
        "https://www.funcionjudicial.gob.ec/normativa",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Solo PDFs
            if ".pdf" not in href.lower(): continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 8: continue
            # Excluir genéricos
            if titulo.lower() in ["ver documento", "descargar", "pdf", "ver", "download"]:
                # Buscar título en el contenedor padre
                parent = link.find_parent(["tr", "li", "div", "article"])
                if parent:
                    titulo = parent.get_text(strip=True)[:200]
            if not href.startswith("http"):
                href = "https://www.funcionjudicial.gob.ec" + href
            num_m = re.search(r"\d{3,4}-\d{4}", titulo)
            data = {
                "titulo": titulo[:300], "numero_norma": num_m.group(0) if num_m else "",
                "numero_ro": None, "jerarquia": "Resolución", "vigencia": "Vigente",
                "fecha_pub": datetime.now().strftime("%Y-%m-%d"),
                "url_pdf": href, "sumario": titulo[:500],
                "origen": "Consejo de la Judicatura",
                "metodo_ocr": "scraper-judicatura",
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
    print("🤖 LexEC Robot Multi-fuente v3")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    fuentes = [
        ("Presidencia",       scrape_presidencia),
        ("Asamblea Nacional", scrape_asamblea),
        ("SERCOP",            scrape_sercop),
        ("Trabajo",           scrape_trabajo),
        ("Salud",             scrape_salud),
        ("Judicatura",        scrape_funcion_judicial),
    ]

    resultados = {}
    for nombre, fn in fuentes:
        try:
            resultados[nombre] = fn()
        except Exception as e:
            print(f"  ❌ {nombre}: {e}")
            resultados[nombre] = 0

    total = sum(resultados.values())
    dur = round(time.time() - t0, 1)
    print("\n" + "=" * 65)
    print("📊 RESUMEN:")
    for nombre, n in resultados.items():
        print(f"  {'✅' if n > 0 else '➖'} {nombre}: {n} normas")
    print(f"\n🎉 TOTAL: {total} normas nuevas — {dur}s")
    print("=" * 65)
    log("GitHub Actions", total, f"{total} normas. " + 
        " | ".join(f"{k}: {v}" for k,v in resultados.items() if v > 0))

if __name__ == "__main__":
    main()
