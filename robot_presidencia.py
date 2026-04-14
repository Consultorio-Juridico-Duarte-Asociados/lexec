import requests
from bs4 import BeautifulSoup
import os
from supabase import create_client
import time

# 1. Configuración de conexión (Usa los secretos que ya tienes en GitHub)
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("--- Iniciando sincronización de Decretos Ejecutivos ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    # Cabeceras para que el servidor nos vea como un navegador real
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9',
    }
    
    try:
        # Intentar la conexión con tiempo de espera de 20 segundos
        response = requests.get(url_fuente, headers=headers, timeout=20)
        response.raise_for_status() 
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Localizamos la tabla de decretos
        tabla = soup.find('table') 
        if not tabla:
            print("Error: No se encontró la tabla de datos en la página.")
            return

        # Obtenemos todas las filas menos la primera (encabezado)
        filas = tabla.find_all('tr')[1:] 
        print(f"Se encontraron {len(filas)} decretos en la página. Procesando...")

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) >= 4:
                num_decreto = cols[0].text.strip()
                fecha_pub = cols[1].text.strip()
                asunto_texto = cols[2].text.strip()
                # Extraer link del PDF
                link_tag = cols[3].find('a')
                link_pdf = link_tag['href'] if link_tag else None

                if link_pdf:
                    # Estructura para tu tabla 'normas' en Supabase
                    data = {
                        "titulo": f"Decreto Ejecutivo No. {num_decreto}",
                        "resumen": asunto_texto,
                        "tipo": "Decreto Ejecutivo",
                        "fecha": fecha_pub,
                        "url_pdf": link_pdf,
                        "institucion": "Presidencia de la República",
                        "estado": "Vigente"
                    }
                    
                    # Guardar o actualizar en Supabase (evita duplicados por título)
                    try:
                        supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                        print(f"✓ Guardado: Decreto {num_decreto}")
                    except Exception as db_err:
                        print(f"x Error al guardar en base de datos: {db_err}")
                    
                    # Pausa de 1 segundo para no saturar al servidor
                    time.sleep(1)

        print("--- Proceso finalizado con éxito ---")

    except requests.exceptions.ConnectionError:
        print("Error: La conexión fue rechazada por el servidor. Reintentando en la próxima ejecución.")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")

if __name__ == "__main__":
    scraping_presidencia()
