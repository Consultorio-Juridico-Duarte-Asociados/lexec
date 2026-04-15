import requests
import re
import os
from bs4 import BeautifulSoup
from supabase import create_client
import time
from datetime import datetime

# Configuración de conexión a Supabase
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

# Fuentes oficiales de la Presidencia
FUENTES = [
    "https://www.presidencia.gob.ec/decretos-ejecutivos/",
    "https://www.presidencia.gob.ec/resoluciones/"
]

def limpiar_fecha(texto_fecha):
    """Convierte texto como '10 de abril 2026' a formato ISO '2026-04-10'"""
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    if not texto_fecha:
        return None
    try:
        texto_fecha = texto_fecha.lower().strip()

        # Formato: "10 de abril de 2026" o "10 de abril 2026"
        m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto_fecha)
        if m:
            dia = m.group(1).zfill(2)
            mes = meses.get(m.group(2), None)
            anio = m.group(3)
            if mes and len(anio) == 4:
                return f"{anio}-{mes}-{dia}"

        # Formato: "10/04/2026" o "10-04-2026"
        m2 = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', texto_fecha)
        if m2:
            return f"{m2.group(3)}-{m2.group(2).zfill(2)}-{m2.group(1).zfill(2)}"

        # Formato ISO: "2026-04-10"
        m3 = re.search(r'(\d{4})-(\d{2})-(\d{2})', texto_fecha)
        if m3:
            return m3.group(0)

        # Formato: "abril 10, 2026" o "abril 2026"
        m4 = re.search(r'(\w+)\s+(\d{1,2}),?\s+(\d{4})', texto_fecha)
        if m4:
            mes = meses.get(m4.group(1), None)
            if mes:
                return f"{m4.group(3)}-{mes}-{m4.group(2).zfill(2)}"

    except Exception as e:
        print(f"   Error procesando fecha '{texto_fecha}': {e}")

    # Si no se pudo parsear la fecha, retornar None para que no se guarde con fecha incorrecta
    return None

def limpiar_numero_ro(texto):
    """
    Extrae y formatea el número de Registro Oficial.
    Retorna formato estándar: 'RO N° 123' o 'RO-S N° 123'
    """
    if not texto:
        return None
    m = re.search(r'(?:RO|Registro\s+Oficial)[^\d]*(\d+)', texto, re.IGNORECASE)
    if m:
        es_suplemento = bool(re.search(r'suplemento', texto, re.IGNORECASE))
        return f"RO-S N° {m.group(1)}" if es_suplemento else f"RO N° {m.group(1)}"
    return None

def procesar_pagina(url):
    print(f"--- Escaneando: {url} ---")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')

        filas = soup.find_all('tr')
        nuevos_registros = 0

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) >= 3:
                num_raw   = cols[0].get_text(strip=True)
                fecha_raw = cols[1].get_text(strip=True)
                asunto_raw = cols[2].get_text(strip=True)
                link = fila.find('a', href=True)

                if not num_raw or "No." == num_raw or not link or ".pdf" not in link['href'].lower():
                    continue

                url_pdf = link['href']

                jerarquia = "Decreto Ejecutivo" if "decretos" in url else "Resolución"

                num_limpio = num_raw.replace("Decreto Ejecutivo", "").replace("No.", "").strip()
                titulo_final = f"{jerarquia} No. {num_limpio}"

                # ── CORRECCIÓN 1: fecha real del decreto, no fecha del sistema ──
                fecha_iso = limpiar_fecha(fecha_raw)
                if not fecha_iso:
                    print(f"   ⚠ Fecha no reconocida: '{fecha_raw}' — usando fecha actual")
                    fecha_iso = datetime.now().strftime('%Y-%m-%d')

                # ── CORRECCIÓN 2: número RO con formato estándar ──
                n_ro = limpiar_numero_ro(asunto_raw)

                data = {
                    "titulo":       titulo_final,
                    "numero_norma": num_limpio,
                    "numero_ro":    n_ro,           # ahora con formato 'RO N° 123'
                    "jerarquia":    jerarquia,
                    "vigencia":     "Vigente",
                    "fecha_pub":    fecha_iso,      # ahora con la fecha real del decreto
                    "url_pdf":      url_pdf,
                    "sumario":      asunto_raw,
                    "origen":       "Presidencia de la República",
                    "metodo_ocr":   "presidencia",
                }

                try:
                    supabase.table("normas").insert(data).execute()
                    print(f"   ✓ {titulo_final} | {fecha_iso} | {n_ro or 'sin RO'}")
                    nuevos_registros += 1
                except Exception:
                    continue

        return nuevos_registros

    except Exception as e:
        print(f"Error técnico en {url}: {e}")
        return 0

def ejecutar_sincronizacion():
    total_general = 0
    for base_url in FUENTES:
        for p in range(1, 4):
            u = base_url if p == 1 else f"{base_url}page/{p}/"
            conteo = procesar_pagina(u)
            total_general += conteo
            if conteo == 0 and p > 1:
                break
            time.sleep(2)

    print(f"\n--- Sincronización Finalizada ---")
    print(f"Total de nuevos documentos en LexEC: {total_general}")

if __name__ == "__main__":
    ejecutar_sincronizacion()
