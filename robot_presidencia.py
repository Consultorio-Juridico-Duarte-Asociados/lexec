"""
LexEC — Robot del Registro Oficial
Fuente: registroficial.gob.ec — PDFs con número y fecha reales
Extrae: Decretos Ejecutivos, Resoluciones, Acuerdos Ministeriales, Ordenanzas
Corre diariamente vía GitHub Actions.
"""
import requests
import re
import os
import json
import time
from bs4 import BeautifulSoup
from supabase import create_client
from datetime import datetime, date

# ── Conexión Supabase ─────────────────────────────────────
supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'es-EC,es;q=0.9',
}

# URLs de las secciones del Registro Oficial
SECCIONES_RO = [
    "https://www.registroficial.gob.ec/245427-2/",   # Registro Oficial ordinario
    "https://www.registroficial.gob.ec/255776-2/",   # Suplemento
]

MESES = {
    'enero':'01','febrero':'02','marzo':'03','abril':'04',
    'mayo':'05','junio':'06','julio':'07','agosto':'08',
    'septiembre':'09','octubre':'10','noviembre':'11','diciembre':'12'
}

# Tipos de normas que queremos extraer (no leyes de Asamblea que ya tiene otro robot)
TIPOS_OBJETIVO = [
    'decreto ejecutivo', 'decreto ley',
    'acuerdo ministerial', 'resolución',
    'ordenanza', 'instructivo', 'circular',
    'reglamento'
]

# ── Helpers ───────────────────────────────────────────────

def limpiar_fecha(texto):
    if not texto: return str(date.today())
    texto = texto.lower().strip()
    m = re.search(r'(\w+),?\s+(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+de\s+)?(\d{4})', texto)
    if m:
        dia = m.group(2).zfill(2)
        mes = MESES.get(m.group(3), '01')
        return f"{m.group(4)}-{mes}-{dia}"
    m2 = re.search(r'(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+de\s+)?(\d{4})', texto)
    if m2:
        dia = m2.group(1).zfill(2)
        mes = MESES.get(m2.group(2), '01')
        return f"{m2.group(3)}-{mes}-{dia}"
    m3 = re.search(r'(\d{4})-(\d{2})-(\d{2})', texto)
    if m3: return m3.group(0)
    return str(date.today())

def ya_existe_ro(numero_ro):
    r = supabase.table("normas").select("id").eq("numero_ro", numero_ro).limit(1).execute()
    return len(r.data) > 0

def ya_existe_pdf(url_pdf):
    r = supabase.table("normas").select("id").eq("url_pdf", url_pdf).limit(1).execute()
    return len(r.data) > 0

def guardar_norma(data):
    try:
        supabase.table("normas").insert(data).execute()
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return False
        print(f"   Error: {e}")
        return False

# ── Extraer texto del PDF ─────────────────────────────────

def extraer_texto_pdf(url_pdf):
    try:
        import fitz
        r = requests.get(url_pdf, headers=HEADERS, timeout=30)
        r.raise_for_status()
        with open("/tmp/ro_temp.pdf", "wb") as f:
            f.write(r.content)
        doc = fitz.open("/tmp/ro_temp.pdf")
        texto = "".join(p.get_text("text") for p in doc)
        doc.close()
        return texto.strip() if len(texto.strip()) > 100 else None
    except Exception as e:
        print(f"   Error PDF: {e}")
        return None

# ── Clasificar con Gemini ─────────────────────────────────

JERARQUIAS = ["Decreto Ejecutivo","Decreto Ley","Reglamento","Ordenanza",
              "Resolución","Acuerdo Ministerial","Circular","Instructivo","Otro"]
TEMATICAS  = ["Tributario","Laboral","Penal","Civil","Ambiental","Salud","Educación",
              "Financiero","Administrativo","Constitucional","Comercial","Familia",
              "Contratación Pública","Seguridad Social","Telecomunicaciones",
              "Energía","Transporte","Agricultura","Minería","Otro"]

def clasificar(texto, numero_ro):
    if not GEMINI_KEY:
        return None
    prompt = f"""Analiza esta norma del Registro Oficial del Ecuador (N° {numero_ro}).
Responde SOLO con JSON válido, sin markdown.

TEXTO (primeras 3000 chars):
{texto[:3000]}

JSON:
{{
  "titulo": "título completo oficial de la norma",
  "numero_norma": "número oficial (ej: Decreto Ejecutivo N° 123) o null",
  "jerarquia": "uno de: {' | '.join(JERARQUIAS)}",
  "origen": "institución que emite (ej: Presidencia de la República, Ministerio de...)",
  "tematica": "una de: {' | '.join(TEMATICAS)}",
  "vigencia": "Vigente",
  "sumario": "resumen de 2-3 oraciones del contenido"
}}"""
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}",
            json={"contents":[{"parts":[{"text":prompt}]}],
                  "generationConfig":{"temperature":0.1,"maxOutputTokens":600}},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r"```(?:json)?|```","",raw).strip()
        d = json.loads(raw)
        if d.get("jerarquia") not in JERARQUIAS: d["jerarquia"] = "Otro"
        if d.get("tematica")  not in TEMATICAS:  d["tematica"]  = "Otro"
        return d
    except Exception as e:
        print(f"   Gemini error: {e}")
        return None

def separar_normas(texto):
    """Divide el texto de una edición en normas individuales."""
    patron = re.compile(
        r"(?=(?:DECRETO\s+(?:EJECUTIVO|LEY)|ACUERDO\s+MINISTERIAL|"
        r"RESOLUCI[ÓO]N|ORDENANZA|REGLAMENTO|CIRCULAR|INSTRUCTIVO)\s)",
        re.IGNORECASE,
    )
    partes = patron.split(texto)
    return [p.strip() for p in partes if len(p.strip()) >= 150]

def extraer_arts(texto, n=5):
    arts = []
    for m in re.finditer(
        r"Art[íi]culo?\s*\.?\s*(\d+)[°º.]?\s*[-–]?\s*([^\n]{15,250})", texto, re.I
    ):
        arts.append(f"Art. {m.group(1)}: {m.group(2).strip()}")
        if len(arts) >= n: break
    return arts

# ── Scraping del Registro Oficial ────────────────────────

def obtener_ediciones_recientes(url_seccion):
    """
    Obtiene las ediciones recientes de una sección del RO.
    Retorna lista de {numero_ro, fecha, url_pdf}
    """
    ediciones = []
    try:
        r = requests.get(url_seccion, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        # Buscar bloques de edición — cada edición tiene número, fecha y link
        # La página muestra: "Año X - Nº NNN", fecha, "Descargar"
        for bloque in soup.find_all(['article', 'div', 'section']):
            texto_bloque = bloque.get_text(' ', strip=True)
            
            # Buscar número de edición
            m_num = re.search(r'N[°º]\s*(\d+)', texto_bloque)
            if not m_num:
                continue
            
            # Buscar fecha
            m_fecha = re.search(
                r'(\w+),?\s+(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+de\s+)?(\d{4})',
                texto_bloque, re.I
            )
            if not m_fecha:
                continue
            
            # Buscar link de descarga
            link = bloque.find('a', href=True, string=re.compile(r'Descargar', re.I))
            if not link:
                link = bloque.find('a', href=re.compile(r'esacc|pdf', re.I))
            if not link:
                continue
            
            numero_ro = f"RO N° {m_num.group(1)}"
            if "suplemento" in url_seccion.lower() or "suplemento" in texto_bloque.lower():
                numero_ro = f"RO-S N° {m_num.group(1)}"
            
            url_pdf = link['href']
            fecha   = limpiar_fecha(texto_bloque)
            
            ediciones.append({
                "numero_ro": numero_ro,
                "fecha":     fecha,
                "url_pdf":   url_pdf,
            })

        print(f"   {len(ediciones)} ediciones encontradas en {url_seccion}")
    except Exception as e:
        print(f"   Error obteniendo ediciones: {e}")
    
    return ediciones

def procesar_edicion(edicion):
    """
    Descarga el PDF de una edición, extrae las normas relevantes y las guarda.
    Omite leyes orgánicas/ordinarias (esas las maneja el robot de Asamblea).
    """
    numero_ro = edicion["numero_ro"]
    url_pdf   = edicion["url_pdf"]
    fecha     = edicion["fecha"]

    # Verificar si ya procesamos esta edición
    if ya_existe_ro(numero_ro) or ya_existe_pdf(url_pdf):
        print(f"   [{numero_ro}] Ya procesada.")
        return 0

    print(f"\n   Procesando {numero_ro} ({fecha})...")
    
    texto = extraer_texto_pdf(url_pdf)
    if not texto:
        print(f"   Sin texto para {numero_ro}")
        return 0

    print(f"   Texto: {len(texto)} chars")

    # Separar normas individuales dentro de la edición
    segmentos = separar_normas(texto)
    
    # Si no se separaron, tratar todo como una norma
    if not segmentos:
        segmentos = [texto]
    
    print(f"   {len(segmentos)} normas detectadas")
    guardadas = 0

    for i, seg in enumerate(segmentos, 1):
        # Detectar tipo de norma en este segmento
        seg_lower = seg.lower()
        
        # Saltar si es ley orgánica u ordinaria (las maneja robot de Asamblea)
        if re.search(r'ley\s+org[aá]nica|ley\s+ordinaria', seg_lower):
            continue
        
        # Solo procesar los tipos que nos interesan
        es_objetivo = any(tipo in seg_lower for tipo in TIPOS_OBJETIVO)
        if not es_objetivo:
            continue

        print(f"   Clasificando norma {i}/{len(segmentos)}...")
        c = clasificar(seg, numero_ro)
        
        if not c:
            # Fallback: detectar jerarquía por palabras clave
            if 'decreto ejecutivo' in seg_lower:
                jerarquia = 'Decreto Ejecutivo'
                origen    = 'Presidencia de la República'
            elif 'acuerdo ministerial' in seg_lower:
                jerarquia = 'Acuerdo Ministerial'
                origen    = 'Ministerio'
            elif 'resolución' in seg_lower:
                jerarquia = 'Resolución'
                origen    = None
            elif 'ordenanza' in seg_lower:
                jerarquia = 'Ordenanza'
                origen    = 'GAD Municipal'
            elif 'reglamento' in seg_lower:
                jerarquia = 'Reglamento'
                origen    = 'Presidencia de la República'
            else:
                jerarquia = 'Otro'
                origen    = None
            
            # Intentar extraer título del texto
            primera_linea = seg.strip().split('\n')[0][:120]
            c = {
                "titulo":    primera_linea or f"Norma del {numero_ro}",
                "numero_norma": None,
                "jerarquia": jerarquia,
                "origen":    origen,
                "tematica":  "Administrativo",
                "vigencia":  "Vigente",
                "sumario":   seg[:300],
            }

        arts = extraer_arts(seg)
        
        norma = {
            "titulo":       c.get("titulo") or f"Norma {numero_ro} — seg. {i}",
            "numero_ro":    numero_ro,
            "numero_norma": c.get("numero_norma"),
            "jerarquia":    c.get("jerarquia", "Otro"),
            "origen":       c.get("origen"),
            "tematica":     c.get("tematica", "Administrativo"),
            "vigencia":     "Vigente",
            "fecha_pub":    fecha,
            "url_pdf":      url_pdf,
            "sumario":      c.get("sumario"),
            "articulos":    arts if arts else None,
            "metodo_ocr":   "registro_oficial",
        }

        if guardar_norma(norma):
            print(f"   ✓ [{norma['jerarquia']}] {norma['titulo'][:60]}")
            guardadas += 1
        
        time.sleep(0.3)

    return guardadas

# ── MAIN ──────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"LexEC — Robot Registro Oficial — {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    total = 0
    
    for seccion in SECCIONES_RO:
        print(f"\n Sección: {seccion}")
        ediciones = obtener_ediciones_recientes(seccion)
        
        for ed in ediciones[:5]:  # Procesar las 5 más recientes por sección
            try:
                total += procesar_edicion(ed)
            except Exception as e:
                print(f"   Error en {ed.get('numero_ro','?')}: {e}")
            time.sleep(1)

    seg = (datetime.now() - inicio).seconds
    print(f"\n{'='*55}")
    print(f"Completado: {total} normas nuevas en {seg}s")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
