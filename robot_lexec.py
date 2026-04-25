#!/usr/bin/env python3
"""
LexEC Robot Extractor — Multi-fuente
Columnas alineadas exactamente con lo que espera la app LexEC.
"""

import os, re, time, hashlib
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

def cod_hash(texto, fuente=""):
    return hashlib.md5((texto + fuente).encode()).hexdigest()[:8]

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠ {url}: {e}")
        return None

def get_existentes():
    try:
        res = supabase.table("normas").select("codigo_unico").execute()
        return {r["codigo_unico"] for r in (res.data or [])}
    except Exception as e:
        print(f"⚠ Error leyendo Supabase: {e}")
        return set()

def norma_base(codigo_unico, titulo, tipo, jerarquia, jerarquia_nombre,
               fecha, fuente, url_fuente, url_pdf, resumen, etiquetas,
               registro_oficial="", numero_ro=""):
    """Construye un dict con EXACTAMENTE las columnas que espera la app LexEC."""
    return {
        "codigo_unico":     codigo_unico,
        "numero_ro":        numero_ro,
        "titulo":           titulo[:400],
        "tipo":             tipo,
        "jerarquia":        jerarquia,
        "jerarquia_nombre": jerarquia_nombre,
        "fecha_publicacion": fecha,
        "fecha_extraccion":  datetime.now().isoformat(),
        "registro_oficial":  registro_oficial,
        "numero_ro_num":     None,
        "suplemento":        None,
        "fuente":            fuente,
        "url_fuente":        url_fuente,
        "url_pdf":           url_pdf,
        "resumen":           resumen[:600],
        "etiquetas":         etiquetas,
        "estado":            "vigente",
        "paginas":           None,
        "articulos":         None,
        "verificado":        False,
        "activo":            True,
    }

def insertar(norma, existentes):
    cod = norma["codigo_unico"]
    if not cod or cod in existentes:
        return False
    try:
        supabase.table("normas").insert(norma).execute()
        existentes.add(cod)
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "23505" in str(e):
            existentes.add(cod)
        else:
            print(f"  ⚠ Insert error: {e}")
        return False

def log(fuente, cantidad, estado, detalles):
    try:
        supabase.table("extracciones").insert({
            "fecha":         datetime.now().isoformat(),
            "fuente":        fuente,
            "cantidad":      cantidad,
            "duracion":      0,
            "estado":        estado,
            "detalles":      detalles,
            "url_rastreada": "github-actions"
        }).execute()
    except: pass

# ── FUENTE 1: Presidencia — Decretos y Resoluciones ───────────────────────────
def scrape_presidencia(existentes):
    fuentes = [
        ("https://www.presidencia.gob.ec/decretos-ejecutivos/", "Decreto Ejecutivo", 4),
        ("https://www.presidencia.gob.ec/resoluciones/",        "Resolución Ejecutiva", 5),
    ]
    total = 0
    for base_url, tipo, jerarquia in fuentes:
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
                titulo = f"{tipo} No. {num}" if num else f"{tipo}: {asunto[:80]}"
                fecha  = limpiar_fecha(fecha_raw)
                cod    = f"PRES-{tipo[:3].upper().replace(' ','-')}-{num or cod_hash(titulo)}-{fecha[:4]}"

                n = norma_base(
                    codigo_unico    = cod,
                    titulo          = titulo,
                    tipo            = tipo,
                    jerarquia       = jerarquia,
                    jerarquia_nombre= tipo,
                    fecha           = fecha,
                    fuente          = "Presidencia de la República",
                    url_fuente      = url,
                    url_pdf         = link["href"],
                    resumen         = asunto[:600],
                    etiquetas       = ["presidencia", tipo.lower().replace(" ","-")],
                )
                if insertar(n, existentes):
                    print(f"  ✅ {titulo} | {fecha}")
                    nuevos += 1; total += 1
            if nuevos == 0 and p > 1: break
            time.sleep(1.5)
    return total

# ── FUENTE 2: Asamblea Nacional — Leyes aprobadas ────────────────────────────
def scrape_asamblea(existentes):
    total = 0
    for p in range(0, 4):
        url = f"https://www.asambleanacional.gob.ec/es/leyes-aprobadas?page={p}"
        soup = get_soup(url)
        if not soup: continue
        nuevos = 0
        for row in soup.find_all(["tr", "li", "article"]):
            link = row.find("a", href=True)
            if not link: continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 15: continue
            href = link["href"]
            if not href.startswith("http"):
                href = "https://www.asambleanacional.gob.ec" + href

            # Buscar fecha y PDF en la fila
            fecha_txt = ""
            for el in row.find_all(["td","span","div","p"]):
                t = el.get_text(strip=True)
                if re.search(r"\d{4}", t) and len(t) < 50:
                    fecha_txt = t; break
            fecha = limpiar_fecha(fecha_txt)

            pdf_a = row.find("a", href=lambda h: h and ".pdf" in h.lower())
            url_pdf = pdf_a["href"] if pdf_a else ""
            if url_pdf and not url_pdf.startswith("http"):
                url_pdf = "https://www.asambleanacional.gob.ec" + url_pdf

            tipo = "Ley Orgánica" if "orgánica" in titulo.lower() else "Ley Ordinaria"
            cod  = f"AN-{re.sub(r'[^a-z0-9]','-',titulo.lower())[:45]}-{fecha[:4]}"

            n = norma_base(
                codigo_unico    = cod,
                titulo          = titulo,
                tipo            = tipo,
                jerarquia       = 3,
                jerarquia_nombre= tipo,
                fecha           = fecha,
                fuente          = "Asamblea Nacional",
                url_fuente      = href,
                url_pdf         = url_pdf,
                resumen         = titulo,
                etiquetas       = ["asamblea-nacional", "ley"],
            )
            if insertar(n, existentes):
                print(f"  ✅ {titulo[:70]}")
                nuevos += 1; total += 1
        if nuevos == 0 and p > 0: break
        time.sleep(2)
    return total

# ── FUENTE 3: Función Judicial — Resoluciones ─────────────────────────────────
def scrape_funcion_judicial(existentes):
    total = 0
    url = "https://www.funcionjudicial.gob.ec/index.php/es/normativa/resoluciones"
    soup = get_soup(url)
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        href = link["href"]
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 10: continue
        if not href.startswith("http"):
            href = "https://www.funcionjudicial.gob.ec" + href
        num_m = re.search(r"(\d{3,4})-(\d{4})", titulo)
        num = num_m.group(0) if num_m else cod_hash(titulo, "FJ")
        cod = f"FJ-RES-{num}"
        fecha_m = re.search(r"\d{4}", titulo)
        fecha = f"{fecha_m.group(0)}-01-01" if fecha_m else datetime.now().strftime("%Y-%m-%d")
        n = norma_base(
            codigo_unico    = cod,
            titulo          = titulo,
            tipo            = "Resolución del Consejo de la Judicatura",
            jerarquia       = 5,
            jerarquia_nombre= "Resolución",
            fecha           = fecha,
            fuente          = "Consejo de la Judicatura",
            url_fuente      = url,
            url_pdf         = href if ".pdf" in href.lower() else "",
            resumen         = titulo,
            etiquetas       = ["judicatura", "resolución"],
        )
        if insertar(n, existentes):
            print(f"  ✅ {titulo[:70]}")
            total += 1
    return total

# ── FUENTE 4: SERCOP — Resoluciones de Contratación Pública ──────────────────
def scrape_sercop(existentes):
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
            num_m = re.search(r"RE-(\d{4}-\d+|\d{3,6})", titulo, re.IGNORECASE)
            num = num_m.group(0) if num_m else cod_hash(titulo, "SERCOP")
            cod = f"SERCOP-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = norma_base(
                codigo_unico    = cod,
                titulo          = titulo,
                tipo            = "Resolución SERCOP",
                jerarquia       = 5,
                jerarquia_nombre= "Resolución",
                fecha           = datetime.now().strftime("%Y-%m-%d"),
                fuente          = "SERCOP",
                url_fuente      = href,
                url_pdf         = href if ".pdf" in href.lower() else "",
                resumen         = titulo,
                etiquetas       = ["sercop", "contratacion-publica"],
            )
            if insertar(n, existentes):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        time.sleep(1)
    return total

# ── FUENTE 5: Ministerio del Trabajo — Acuerdos Ministeriales ────────────────
def scrape_trabajo(existentes):
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
        num = num_m.group(0) if num_m else cod_hash(titulo, "MDT")
        cod = f"MDT-AM-{re.sub(r'[^a-z0-9]','-',num.lower())}"
        n = norma_base(
            codigo_unico    = cod,
            titulo          = titulo,
            tipo            = "Acuerdo Ministerial",
            jerarquia       = 5,
            jerarquia_nombre= "Acuerdo Ministerial",
            fecha           = datetime.now().strftime("%Y-%m-%d"),
            fuente          = "Ministerio del Trabajo",
            url_fuente      = href,
            url_pdf         = href if ".pdf" in href.lower() else "",
            resumen         = titulo,
            etiquetas       = ["trabajo", "acuerdo-ministerial"],
        )
        if insertar(n, existentes):
            print(f"  ✅ {titulo[:70]}")
            total += 1
    return total

# ── FUENTE 6: SRI — Resoluciones Tributarias ─────────────────────────────────
def scrape_sri(existentes):
    total = 0
    for url in [
        "https://www.sri.gob.ec/web/guest/resoluciones-sunat",
        "https://www.sri.gob.ec/web/guest/circulares",
    ]:
        soup = get_soup(url)
        if not soup: continue
        for link in soup.find_all("a", href=True):
            href = link["href"]
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 10: continue
            if not href.startswith("http"): href = "https://www.sri.gob.ec" + href
            num_m = re.search(r"NAC-DGERCGC\d+-\d+|NAC-\w+\d+|NACC-DGERCGC\d+", titulo)
            num = num_m.group(0) if num_m else cod_hash(titulo, "SRI")
            cod = f"SRI-{re.sub(r'[^a-z0-9]','-',num.lower())}"
            n = norma_base(
                codigo_unico    = cod,
                titulo          = titulo,
                tipo            = "Resolución Tributaria",
                jerarquia       = 5,
                jerarquia_nombre= "Resolución SRI",
                fecha           = datetime.now().strftime("%Y-%m-%d"),
                fuente          = "SRI",
                url_fuente      = href,
                url_pdf         = href if ".pdf" in href.lower() else "",
                resumen         = titulo,
                etiquetas       = ["sri", "tributario"],
            )
            if insertar(n, existentes):
                print(f"  ✅ {titulo[:70]}")
                total += 1
        time.sleep(1)
    return total

# ── FUENTE 7: Ministerio de Salud ────────────────────────────────────────────
def scrape_salud(existentes):
    total = 0
    soup = get_soup("https://www.salud.gob.ec/acuerdos-ministeriales/")
    if not soup: return 0
    for link in soup.find_all("a", href=True):
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 10: continue
        href = link["href"]
        if not href.startswith("http"): href = "https://www.salud.gob.ec" + href
        num_m = re.search(r"AM\s*\d+|ARCSA-\w+-\d+|\d{3,4}-\d{4}", titulo)
        num = num_m.group(0) if num_m else cod_hash(titulo, "MSP")
        cod = f"MSP-{re.sub(r'[^a-z0-9]','-',num.lower())}"
        n = norma_base(
            codigo_unico    = cod,
            titulo          = titulo,
            tipo            = "Acuerdo Ministerial",
            jerarquia       = 5,
            jerarquia_nombre= "Acuerdo Ministerial de Salud",
            fecha           = datetime.now().strftime("%Y-%m-%d"),
            fuente          = "Ministerio de Salud Pública",
            url_fuente      = href,
            url_pdf         = href if ".pdf" in href.lower() else "",
            resumen         = titulo,
            etiquetas       = ["salud", "acuerdo-ministerial"],
        )
        if insertar(n, existentes):
            print(f"  ✅ {titulo[:70]}")
            total += 1
    return total

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=" * 65)
    print("🤖 LexEC Robot Multi-fuente")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    existentes = get_existentes()
    print(f"📚 Normas en Supabase: {len(existentes)}\n")

    FUENTES = [
        ("Presidencia (Decretos/Resoluciones)", scrape_presidencia),
        ("Asamblea Nacional",                   scrape_asamblea),
        ("Función Judicial",                    scrape_funcion_judicial),
        ("SERCOP",                              scrape_sercop),
        ("Ministerio del Trabajo",              scrape_trabajo),
        ("SRI",                                 scrape_sri),
        ("Ministerio de Salud",                 scrape_salud),
    ]

    resultados = {}
    for nombre, fn in FUENTES:
        print(f"📌 {nombre}")
        try:
            n = fn(existentes)
            resultados[nombre] = n
        except Exception as e:
            print(f"  ❌ Error: {e}")
            resultados[nombre] = 0
        print()

    total = sum(resultados.values())
    dur   = round(time.time() - t0, 1)

    print("=" * 65)
    print("📊 RESUMEN FINAL:")
    for nombre, n in resultados.items():
        emoji = "✅" if n > 0 else "➖"
        print(f"  {emoji} {nombre}: {n} normas nuevas")
    print(f"\n🎉 TOTAL: {total} normas nuevas — {dur}s")
    print("=" * 65)

    resumen = " | ".join(f"{k.split('(')[0].strip()}: {v}" for k, v in resultados.items() if v > 0)
    log("GitHub Actions", total,
        "exitoso" if total >= 0 else "error",
        f"{total} normas nuevas. {resumen or 'Sin nuevas normas (ya al día)'}")

if __name__ == "__main__":
    main()
