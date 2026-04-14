import requests
from bs4 import BeautifulSoup
import os
from supabase import create_client
import time

# Configuración de conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("--- Iniciando sincronización de Decretos Ejecutivos (Modo Avanzado) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    # Cabeceras de alto nivel para saltar protecciones
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # Usamos una sesión para mantener cookies si fuera necesario
        session = requests.Session()
        response = session.get(url_fuente, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"Error de acceso: Código {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Intentamos localizar la tabla por múltiples vías
        # 1. Por etiqueta table, 2. Por clase común, 3. Por el contenedor del artículo
        tabla = soup.find('table') or soup.find(class_='entry-content') or soup.find('article')
        
        if not tabla:
            print("Error: No se encontró el contenedor de datos.")
            return

        # Buscamos todas las filas
        filas = tabla.find_all('tr')
        
        # Si no hay filas de tabla, buscamos enlaces de descarga directos (plan B)
        if len(filas) < 2:
            print("Buscando enlaces directos por falta de tabla...")
            enlaces = tabla.find_all('a', href=True)
            for link in enlaces:
                if '.pdf' in link['href'].lower() and 'decreto' in link.text.lower():
                    # Lógica simplificada para enlaces sueltos
                    titulo_limpio = link.text.strip() or "Decreto Ejecutivo Nuevo"
                    guardar_en_supabase(titulo_limpio, "Consulte el documento", link['href'], "Reciente")
        else:
            print(f"Filas encontradas: {len(filas)}. Procesando datos...")
            for fila in filas:
                cols = fila.find_all('td')
                if len(cols) >= 3:
                    num = cols[0].get_text(strip=True)
                    # Saltamos si es el encabezado
                    if "No" in num or "Nro" in num or not num: continue
                    
                    fec = cols[1].get_text(strip=True)
                    asu = cols[2].get_text(strip=True)
                    link_tag = fila.find('a', href=True)
                    link_pdf = link_tag['href'] if link_tag else None

                    if link_pdf:
                        guardar_en_supabase(f"Decreto Ejecutivo No. {num}", asu, link_pdf, fec)
                        time.sleep(0.5)

        print("--- Proceso finalizado ---")

    except Exception as e:
        print(f"Error crítico: {e}")

def guardar_en_supabase(titulo, resumen, url, fecha):
    try:
        data = {
            "titulo": titulo,
            "resumen": resumen,
            "tipo": "Decreto Ejecutivo",
            "fecha": fecha,
            "url_pdf": url,
            "institucion": "Presidencia de la República",
            "estado": "Vigente"
        }
        supabase.table("normas").upsert(data, on_conflict="titulo").execute()
        print(f"✓ {titulo} procesado.")
    except Exception as e:
        print(f"Error al insertar: {e}")

if __name__ == "__main__":
    scraping_presidencia()
