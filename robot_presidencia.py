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
    try:
        texto_fecha = texto_fecha.lower()
        # Busca el día, el mes y el año en el texto
        partes = re.findall(r'\w+', texto_fecha)
        if len(partes) >= 3:
            dia = partes[0].zfill(2)
            # Buscamos el mes por nombre; partes[1] suele ser 'de'
            mes_nombre = next((m for m in meses if m in texto_fecha), '01')
            mes = meses[mes_nombre]
            anio = partes[-1]
            # Validar que el año sea un número de 4 dígitos
            if len(anio) == 4 and anio.isdigit():
                return f"{anio}-{mes}-{dia}"
    except Exception as e:
        print(f"Error al procesar fecha '{texto_fecha}': {e}")
    
    # Si falla, devuelve la fecha actual del sistema
    return datetime.now().strftime('%Y-%m-%d')

def procesar_pagina(url):
    print(f"--- Escaneando: {url} ---")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Localizamos la tabla de documentos
        filas = soup.find_all('tr')
        nuevos_registros = 0

        for fila in filas:
            cols = fila.find_all('td')
            # Las tablas de Presidencia suelen tener: Número, Fecha, Asunto/Enlace
            if len(cols) >= 3:
                num_raw = cols[0].get_text(strip=True)
                fecha_raw = cols[1].get_text(strip=True)
                asunto_raw = cols[2].get_text(strip=True)
                link = fila.find('a', href=True)
                
                # Ignorar filas de encabezado o sin PDF
                if not num_raw or "No." == num_raw or not link or ".pdf" not in link['href'].lower():
                    continue

                url_pdf = link['href']
                
                # Definir jerarquía y limpiar título
                jerarquia = "Decreto Ejecutivo" if "decretos" in url else "Resolución"
                
                # Limpiar el número de norma (quitar prefijos repetidos)
                num_limpio = num_raw.replace("Decreto Ejecutivo", "").replace("No.", "").strip()
                titulo_final = f"{jerarquia} No. {num_limpio}"
                
                # Procesar la fecha real del documento
                fecha_iso = limpiar_fecha(fecha_raw)

                # Intentar extraer Registro Oficial del texto si existe
                ro_match = re.search(r'(?:RO|Registro Oficial)(?:\s+N°|No\.?|)\s*(\d+)', asunto_raw, re.IGNORECASE)
                n_ro = ro_match.group(1) if ro_match else "Por publicar"

                # Estructura final basada en tu base de datos Supabase
                data = {
                    "titulo": titulo_final,
                    "numero_norma": num_limpio,
                    "numero_ro": n_ro,
                    "jerarquia": jerarquia,
                    "vigencia": "Vigente",
                    "fecha_pub": fecha_iso, 
                    "url_pdf": url_pdf,
                    "sumario": asunto_raw,
                    "origen": "Presidencia"
                }
                
                try:
                    # Insertamos el registro
                    supabase.table("normas").insert(data).execute()
                    print(f"   ✓ Guardado: {titulo_final} | Fecha: {fecha_iso}")
                    nuevos_registros += 1
                except Exception:
                    # Si ya existe o hay error de duplicado, saltamos silenciosamente
                    continue 

        return nuevos_registros

    except Exception as e:
        print(f"Error técnico en la página {url}: {e}")
        return 0

def ejecutar_sincronizacion():
    total_general = 0
    for base_url in FUENTES:
        # Escaneamos 3 páginas de profundidad para capturar el historial reciente
        for p in range(1, 4):
            u = base_url if p == 1 else f"{base_url}page/{p}/"
            conteo = procesar_pagina(u)
            total_general += conteo
            
            # Si una página no devuelve nada nuevo, es probable que ya estemos al día
            if conteo == 0 and p > 1:
                break
            time.sleep(2) # Pausa de cortesía entre páginas

    print(f"\n--- Sincronización Finalizada ---")
    print(f"Total de nuevos documentos en LexEC: {total_general}")

if __name__ == "__main__":
    ejecutar_sincronizacion()
