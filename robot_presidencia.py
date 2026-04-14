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
    print("--- Iniciando Sincronización LexEC (Protocolo Directo) ---")
    # Usamos la URL principal de decretos
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    # Cabeceras ultra-reales para evitar el bloqueo de "contenedor no encontrado"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Referer': 'https://www.google.com/',
        'DNT': '1',
        'Connection': 'keep-alive',
    }
    
    try:
        session = requests.Session()
        # Primer intento: Cargar la página
        response = session.get(url_fuente, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"Error de acceso: Código {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # BUSQUEDA AGRESIVA: Si no encuentra tabla, busca cualquier fila (tr) en toda la página
        filas = soup.find_all('tr')
        
        if not filas or len(filas) < 2:
            print("Aviso: No se detectó tabla estándar. Intentando búsqueda por enlaces PDF...")
            # Plan B: Buscar todos los enlaces que contengan la palabra 'Decreto' y terminen en .pdf
            enlaces = soup.find_all('a', href=True)
            encontrados = 0
            for link in enlaces:
                url_pdf = link['href']
                texto = link.get_text().strip()
                if ".pdf" in url_pdf.lower() and ("decreto" in texto.lower() or "dec" in texto.lower()):
                    guardar_en_supabase(f"Decreto Ejecutivo: {texto}", texto, url_pdf, "2024-2025")
                    encontrados += 1
            
            if encontrados == 0:
                print("Error: El servidor entregó una página vacía o protegida.")
                return
        else:
            print(f"Se detectaron {len(filas)} filas. Procesando...")
            for fila in filas:
                cols = fila.find_all('td')
                if len(cols) >= 3:
                    num = cols[0].get_text(strip=True)
                    # Saltar encabezados
                    if "No" in num or "Nro" in num or not num: continue
                    
                    fec = cols[1].get_text(strip=True)
                    asu = cols[2].get_text(strip=True)
                    link_tag = fila.find('a', href=True)
                    link_pdf = link_tag['href'] if link_tag else None

                    if link_pdf:
                        guardar_en_supabase(f"Decreto Ejecutivo No. {num}", asu, link_pdf, fec)
                        time.sleep(1)

        print("--- Proceso LexEC finalizado ---")

    except Exception as e:
        print(f"Error crítico en la ejecución: {e}")

def guardar_en_supabase(titulo, resumen, url, fecha):
    try:
        # Limpiar URL si es relativa
        if url.startswith('/'):
            url = "https://www.presidencia.gob.ec" + url
            
        data = {
            "titulo": titulo,
            "resumen": resumen,
            "tipo": "Decreto Ejecutivo",
            "fecha": fecha,
            "url_pdf": url,
            "institucion": "Presidencia de la República",
            "estado": "Vigente"
        }
        # Evitar duplicados por título
        supabase.table("normas").upsert(data, on_conflict="titulo").execute()
        print(f"✓ {titulo} sincronizado.")
    except Exception as e:
        print(f"Error al guardar: {e}")

if __name__ == "__main__":
    scraping_presidencia()
