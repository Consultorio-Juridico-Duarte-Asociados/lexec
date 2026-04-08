# LexEC — Sistema Automático de Normas Ecuatorianas

El scraper corre solo todos los días a las 7 AM (Ecuador).
Descarga el Registro Oficial → extrae texto → clasifica con IA → guarda en Supabase.

## Archivos importantes

| Archivo | Qué hace |
|---------|----------|
| `scraper/scraper.py` | El robot que descarga y clasifica normas |
| `scraper/requirements.txt` | Librerías que necesita el robot |
| `.github/workflows/scraper.yml` | Le dice a GitHub cuándo correr el robot |
| `supabase_schema.sql` | Crea las tablas en la base de datos |
| `normas_iniciales.csv` | 12 normas reales para cargar al inicio |

## Credenciales necesarias (GitHub Secrets)

| Secret | Dónde obtenerlo |
|--------|----------------|
| `SUPABASE_URL` | Supabase → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase → Settings → API → service_role key |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
