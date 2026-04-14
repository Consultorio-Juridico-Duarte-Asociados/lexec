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
    print("--- Iniciando sincronización de Decretos Ejecutivos ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Búsqueda más flexible de la tabla
        # Intentamos buscar por etiqueta, pero también por clases comunes en WordPress (que usa la Presidencia)
        tabla = soup.find('table') or soup.find(class_='wp-block-table') or soup.find('tbody')
        
        if not tabla:
            # Si aún no aparece, imprimimos un poco del contenido para diagnóstico
            print("Error: No se encontró la tabla. Estructura de página detectada parcialmente.")
            return

        filas = tabla.find_all('tr')
        print(f"Filas detectadas: {len(filas)}. Procesando...")

        for fila in filas:
            cols = fila.find_all('td')
            # Verificamos que sea una fila con datos (mínimo 3 o 4 columnas)
            if len(cols) >= 3:
                # Limpiamos los textos
                num_decreto = cols[0].get_text(strip=True)
                
                # Evitamos procesar la fila de encabezado si el primer campo dice "No." o "Número"
                if "No" in num_decreto or "Nro" in num_decreto:
                    continue
                    
                fecha_pub = cols[1].get_text(strip=True)
                asunto_texto = cols[2].get_text(strip=True)
                
                # Buscamos el link en cualquier parte de la fila por si no está en la última columna
                link_tag = fila.find('a', href=True)
                link_pdf = link_tag['href'] if link_tag else None

                if link_pdf and num_decreto:
                    data = {
                        "titulo": f"Decreto Ejecutivo No. {num_decreto}",
                        "resumen": asunto_texto,
                        "tipo": "Decreto Ejecutivo",
                        "fecha": fecha_pub,
                        "url_pdf": link_pdf,
                        "institucion": "Presidencia de la República",
                        "estado": "Vigente"
                    }
                    
                    try:
                        supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                        print(f"✓ Guardado: Decreto {num_decreto}")
                    except Exception as db_err:
                        print(f"x Error en Supabase: {db_err}")
                    
                    time.sleep(0.5)

        print("--- Proceso finalizado ---")

    except Exception as e:
        print(f"Ocurrió un error: {e}")

if __name__ == "__main__":
    scraping_presidencia()
