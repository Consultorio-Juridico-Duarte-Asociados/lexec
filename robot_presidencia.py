"""
LexEC — Robot de Decretos Ejecutivos y Resoluciones
Fuente: presidencia.gob.ec + minka.presidencia.gob.ec
Corre diariamente vía GitHub Actions.
"""
import requests
import re
import os
import time
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import datetime, date

# ── Conexión Supabase ─────────────────────────────────────
supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'es-EC,es;q=0.9',
}

MESES = {
    'enero':'01','febrero':'02','marzo':'03','abril':'04',
    'mayo':'05','junio':'06','julio':'07','agosto':'08',
    'septiembre':'09','octubre':'10','noviembre':'11','diciembre':'12'
}

# ── Helpers ───────────────────────────────────────────────

def limpiar_fecha(texto):
    """Convierte '10 de abril de 2026' → '2026-04-10'"""
    if not texto:
        return str(date.today())
    texto = texto.lower().strip()
    # Formato: dd de mes de yyyy
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto)
    if m:
        dia = m.group(1).zfill(2)
        mes = MESES.get(m.group(2), '01')
        return f"{m.group(3)}-{mes}-{dia}"
    # Formato: dd/mm/yyyy
    m2 = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', texto)
    if m2:
        return f"{m2.group(3)}-{m2.group(2).zfill(2)}-{m2.group(1).zfill(2)}"
    # Formato: yyyy-mm-dd
    m3 = re.search(r'(\d{4})-(\d{2})-(\d{2})', texto)
    if m3:
        return m3.group(0)
    return str(date.today())

def ya_existe(titulo=None, url_pdf=None):
    """Verifica si ya existe en Supabase por URL de PDF o título."""
    if url_pdf:
        r = supabase.table("normas").select("id").eq("url_pdf", url_pdf).limit(1).execute()
        if r.data:
            return True
    if titulo:
        r = supabase.table("normas").select("id").ilike("titulo", f"%{titulo[:50]}%").limit(1).execute()
        if r.data:
            return True
    return False

def guardar_norma(data):
    """Guarda una norma en Supabase. Retorna True si se guardó."""
    try:
        supabase.table("normas").insert(data).execute()
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return False  # Ya existe, no es error
        print(f"   Error guardando: {e}")
        return False

# ── FUENTE 1: presidencia.gob.ec/decretos-ejecutivos ─────
# La página tiene PDFs con links directos, no tabla

def scrapear_presidencia_decretos():
    """
    Extrae PDFs de decretos directamente desde presidencia.gob.ec.
    La página tiene links a PDFs con nombres descriptivos.
    """
    url = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    print(f"\n  Escaneando: {url}")
    nuevos = 0

    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Buscar todos los links a PDFs
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' not in href.lower():
                continue

            url_pdf = href if href.startswith('http') else f"https://www.presidencia.gob.ec{href}"

            # Extraer número del decreto del nombre del archivo o del texto
            texto_link = a.get_text(strip=True) or ''
            nombre_archivo = href.split('/')[-1].replace('.pdf','').replace('-',' ').replace('_',' ')

            # Buscar número de decreto
            m_num = re.search(r'(?:decreto|DE)[_\-\s]*(?:ejecutivo[_\-\s]*)?(?:No\.?\s*)?(\d+)', 
                            nombre_archivo + ' ' + texto_link, re.I)
            numero = m_num.group(1) if m_num else re.search(r'\d+', nombre_archivo)
            numero = numero.group(0) if hasattr(numero, 'group') else str(numero) if numero else '?'

            titulo = f"Decreto Ejecutivo No. {numero}"
            
            # Extraer descripción del nombre de archivo
            desc = re.sub(r'decreto[_\-\s]*ejecutivo[_\-\s]*no?[_\-\s]*\d+[_\-\s]*', '', 
                         nombre_archivo, flags=re.I).strip().title()
            if desc:
                titulo = f"Decreto Ejecutivo No. {numero} — {desc}"

            if ya_existe(url_pdf=url_pdf):
                print(f"   Ya existe: {titulo[:55]}")
                continue

            data = {
                "titulo":       titulo,
                "numero_norma": f"Decreto Ejecutivo No. {numero}",
                "numero_ro":    None,
                "jerarquia":    "Decreto Ejecutivo",
                "origen":       "Presidencia de la República",
                "tematica":     "Administrativo",
                "vigencia":     "Vigente",
                "fecha_pub":    str(date.today()),
                "url_pdf":      url_pdf,
                "sumario":      f"Decreto Ejecutivo No. {numero} emitido por la Presidencia de la República del Ecuador.",
                "metodo_ocr":   "presidencia",
            }

            if guardar_norma(data):
                print(f"   ✓ {titulo[:65]}")
                nuevos += 1

    except Exception as e:
        print(f"   Error: {e}")

    return nuevos


# ── FUENTE 2: minka.presidencia.gob.ec ───────────────────
# Portal oficial con tabla de decretos estructurada

def scrapear_minka():
    """
    Extrae decretos del portal MINKA de la Presidencia.
    Este portal tiene una tabla estructurada con número, fecha y asunto.
    """
    url = "https://minka.presidencia.gob.ec/portal/usuarios_externos.jsf"
    print(f"\n  Escaneando MINKA: {url}")
    nuevos = 0

    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            print(f"   MINKA devolvió {r.status_code}")
            return 0

        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Buscar tabla de decretos
        tabla = soup.find('table')
        if not tabla:
            print("   MINKA: no se encontró tabla")
            return 0

        filas = tabla.find_all('tr')
        print(f"   {len(filas)} filas encontradas")

        for fila in filas[1:]:  # saltar encabezado
            cols = fila.find_all('td')
            if len(cols) < 3:
                continue

            num_raw    = cols[0].get_text(strip=True)
            fecha_raw  = cols[1].get_text(strip=True)
            asunto_raw = cols[2].get_text(strip=True)
            link       = fila.find('a', href=True)

            if not num_raw or not link:
                continue

            url_pdf = link['href']
            if not url_pdf.startswith('http'):
                url_pdf = f"https://minka.presidencia.gob.ec{url_pdf}"

            # Solo PDFs
            if '.pdf' not in url_pdf.lower() and 'download' not in url_pdf.lower():
                continue

            num_limpio = re.sub(r'(?i)decreto\s*ejecutivo\s*no?\.?\s*', '', num_raw).strip()
            titulo     = f"Decreto Ejecutivo No. {num_limpio}"
            if asunto_raw and len(asunto_raw) > 5:
                titulo = f"Decreto Ejecutivo No. {num_limpio} — {asunto_raw[:80]}"

            fecha_iso = limpiar_fecha(fecha_raw)

            # RO en el asunto
            m_ro = re.search(r'(?:RO|Registro Oficial)[^\d]*(\d+)', asunto_raw, re.I)
            n_ro = f"RO N° {m_ro.group(1)}" if m_ro else None

            if ya_existe(url_pdf=url_pdf):
                continue

            data = {
                "titulo":       titulo,
                "numero_norma": f"Decreto Ejecutivo No. {num_limpio}",
                "numero_ro":    n_ro,
                "jerarquia":    "Decreto Ejecutivo",
                "origen":       "Presidencia de la República",
                "tematica":     "Administrativo",
                "vigencia":     "Vigente",
                "fecha_pub":    fecha_iso,
                "url_pdf":      url_pdf,
                "sumario":      asunto_raw or titulo,
                "metodo_ocr":   "minka",
            }

            if guardar_norma(data):
                print(f"   ✓ {titulo[:65]}")
                nuevos += 1

    except Exception as e:
        print(f"   Error MINKA: {e}")

    return nuevos


# ── FUENTE 3: Acuerdos Ministeriales recientes ───────────
# Algunos ministerios publican sus acuerdos en sus propios sitios

def scrapear_acuerdos_ministeriales():
    """
    Extrae acuerdos ministeriales de ministerios que los publican abiertamente.
    """
    fuentes_ministerios = [
        {
            "url": "https://www.trabajo.gob.ec/acuerdos-ministeriales/",
            "origen": "Ministerio de Trabajo",
            "jerarquia": "Acuerdo Ministerial",
        },
        {
            "url": "https://www.ambiente.gob.ec/acuerdos-ministeriales/",
            "origen": "Ministerio del Ambiente",
            "jerarquia": "Acuerdo Ministerial",
        },
    ]

    nuevos = 0
    for fuente in fuentes_ministerios:
        print(f"\n  Escaneando: {fuente['url']}")
        try:
            r = requests.get(fuente['url'], headers=HEADERS, timeout=20)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, 'html.parser')

            for a in soup.find_all('a', href=True):
                href = a['href']
                if '.pdf' not in href.lower():
                    continue

                url_pdf = href if href.startswith('http') else f"{fuente['url'].split('/acuerdos')[0]}{href}"
                texto   = a.get_text(strip=True)
                
                if not texto or len(texto) < 5:
                    nombre = href.split('/')[-1].replace('.pdf','').replace('-',' ').replace('_',' ')
                    texto  = nombre.title()

                if ya_existe(url_pdf=url_pdf):
                    continue

                data = {
                    "titulo":    f"{fuente['jerarquia']} — {texto[:100]}",
                    "jerarquia": fuente['jerarquia'],
                    "origen":    fuente['origen'],
                    "tematica":  "Administrativo",
                    "vigencia":  "Vigente",
                    "fecha_pub": str(date.today()),
                    "url_pdf":   url_pdf,
                    "sumario":   texto,
                    "metodo_ocr":"ministerio",
                }

                if guardar_norma(data):
                    print(f"   ✓ {data['titulo'][:65]}")
                    nuevos += 1

        except Exception as e:
            print(f"   Error {fuente['origen']}: {e}")
        time.sleep(1)

    return nuevos


# ── MAIN ──────────────────────────────────────────────────

def ejecutar_sincronizacion():
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"LexEC — Robot Presidencia — {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    total = 0
    total += scrapear_presidencia_decretos()
    time.sleep(2)
    total += scrapear_minka()
    time.sleep(2)
    total += scrapear_acuerdos_ministeriales()

    seg = (datetime.now() - inicio).seconds
    print(f"\n{'='*55}")
    print(f"Completado: {total} nuevos documentos en {seg}s")
    print(f"{'='*55}")

if __name__ == "__main__":
    ejecutar_sincronizacion()
