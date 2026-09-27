# StackSignal publisher

Generador estático independiente para comparativas técnicas, recursos para desarrolladores y guías de decisión. Produce páginas rápidas con tabla comparativa, especificaciones, preguntas frecuentes, fuentes primarias, datos estructurados y enlaces de afiliado declarados.

## Qué incluye

- Generación estática desde JSON con HTML, Markdown y JSON derivados de la misma fuente.
- Borradores `noindex,nofollow` hasta que un editor cambia su estado a `reviewed`.
- Puerta de calidad obligatoria para títulos, descripción, criterios, FAQs, fuentes y revisión.
- Hash de contenido y restricción única en SQLite para evitar duplicados.
- Inyección fija del tag `blackboxia92-21` en enlaces Amazon válidos.
- Aviso de comisión general y contextual junto a cada bloque de enlaces de Amazon.
- Atributos `rel="sponsored nofollow noopener"` en enlaces afiliados.
- `TechArticle`, `BreadcrumbList` e `ItemList` en JSON-LD, sin `Product`, `Review`, precios, ratings ni disponibilidad inventados.
- Sitemap XML automático, fragmentado cada 45.000 URLs, con sólo páginas editoriales públicas y hubs de StackSignal.
- `robots.txt`, URLs canónicas y fechas `lastmod`.
- Cola incremental de URLs modificadas para IndexNow, en lotes de hasta 10.000.
- Contenedor de producción con Nginx y puerto 8080.
- Analítica privada sin cookies mediante una función de Netlify y almacenamiento persistente en Netlify Blobs.

## Principio editorial

Una página sólo entra al sitemap y a la cola IndexNow cuando tiene evidencia primaria, criterios completos, una conclusión útil y `status: "reviewed"`. Los catálogos archivados `mass-products-v1` y `consumer-products-v1` se preservan como fuente histórica, pero el generador los excluye de HTML público, feeds, navegación, sitemap y IndexNow. Este control evita convertir combinaciones de palabras clave en páginas vacías.

La estructura ayuda a lectores y sistemas automáticos a entender el contenido. No garantiza citas en modelos de lenguaje, rich results ni posiciones de búsqueda.

## Instalación local

Requiere Python 3.11 o posterior.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Construir el sitio de ejemplo:

```powershell
python -m publisher build `
  --content content/pages `
  --output dist `
  --state data/state.sqlite3 `
  --base-url https://tu-dominio.com
```

Vista previa:

```powershell
python -m http.server 8080 --directory dist
```

Abrir `http://localhost:8080/`.

## Flujo masivo seguro

`content/catalog.json` contiene productos agrupados por categoría y audiencias. La expansión crea todas las parejas dentro de cada categoría por cada audiencia:

```powershell
python -m publisher expand --catalog content/catalog.json --output content/pages/drafts
```

Con 100 herramientas de una categoría y 20 audiencias, la matriz puede producir 99.000 briefs. Todos quedan en `draft`, sin sitemap y sin IndexNow. Se puede limitar una corrida:

```powershell
python -m publisher expand --limit 1000
```

Para revisar un brief:

1. Sustituir textos pendientes por investigación propia y fuentes oficiales.
2. Completar al menos tres criterios, tres FAQs y dos fuentes primarias.
3. Escribir un veredicto que explique para quién conviene cada opción.
4. Establecer `reviewed_by`, actualizar la fecha y cambiar `status` a `reviewed`.
5. Volver a construir. Sólo esa página pasa al sitemap y a la cola IndexNow.

Los borradores pueden renderizarse para revisión interna con `--include-drafts`; permanecen con `noindex,nofollow` y viven bajo `/drafts/`.

## Enlaces de Amazon

Cada recurso admite un ASIN o ISBN-10:

```json
{
  "title": "Designing Data-Intensive Applications",
  "asin": "1449373321",
  "note": "Por qué este recurso ayuda al lector."
}
```

El dominio configurado es `amazon.es` y el tag está fijado por código a `blackboxia92-21`. El generador rechaza otra etiqueta. No almacena precios, reseñas, imágenes ni disponibilidad de Amazon.

Amazon exige que la cuenta de Associates esté aprobada para el sitio y el marketplace usados. El tag por sí solo no acredita esa aprobación.

## IndexNow

Generar una clave:

```powershell
python -m publisher key
```

Construir con la clave crea `dist/<CLAVE>.txt`:

```powershell
python -m publisher build --base-url https://tu-dominio.com --indexnow-key TU_CLAVE
```

Después de publicar `dist`, comprobar el lote sin enviarlo:

```powershell
python -m publisher notify --base-url https://tu-dominio.com --key TU_CLAVE --dry-run
```

Enviar cambios:

```powershell
python -m publisher notify --base-url https://tu-dominio.com --key TU_CLAVE
```

El comando verifica primero que `https://tu-dominio.com/TU_CLAVE.txt` devuelva la clave exacta. Una respuesta 200 o 202 de IndexNow confirma recepción, no indexación.

### Operación post-deploy

Netlify publica primero los archivos estáticos y no conserva la base SQLite temporal de una build. Por eso la notificación se hace de forma explícita después de confirmar el deploy de producción, usando un estado persistente local o de CI que no se debe commitear:

```powershell
# Una vez por cambio editorial, construir con el mismo estado persistente.
.\.venv\Scripts\python.exe -m publisher build `
  --content content/pages `
  --output dist `
  --state data/indexnow-state.sqlite3 `
  --base-url https://stacksignal-tech.netlify.app `
  --indexnow-key (Get-Content indexnow-key.txt -Raw).Trim()

# Tras verificar que el deploy de Netlify está live, revisar y enviar sólo las URLs cambiadas.
.\.venv\Scripts\python.exe -m publisher notify `
  --state data/indexnow-state.sqlite3 `
  --base-url https://stacksignal-tech.netlify.app `
  --key (Get-Content indexnow-key.txt -Raw).Trim() `
  --dry-run
.\.venv\Scripts\python.exe -m publisher notify `
  --state data/indexnow-state.sqlite3 `
  --base-url https://stacksignal-tech.netlify.app `
  --key (Get-Content indexnow-key.txt -Raw).Trim()
```

`indexnow-key.txt` is a public verification file, not a credential. Never add Search Console, Bing, Netlify, or other account tokens to Git. Do not use Google Indexing API for normal guides.

## Discovery and measurement

- Submit `https://stacksignal-tech.netlify.app/sitemap.xml` in Google Search Console and Bing Webmaster Tools.
- In Google Search Console create a **URL-prefix** property for `https://stacksignal-tech.netlify.app/`, choose the HTML tag method, set the returned `content` value (not the whole tag) as Netlify production environment variable `GOOGLE_SITE_VERIFICATION`, then deploy and click Verify.
- In Bing Webmaster Tools add the same URL-prefix property, choose the meta-tag method, set its returned value as Netlify production environment variable `BING_SITE_VERIFICATION`, deploy, and click Verify. (DNS verification is unavailable unless StackSignal later owns a custom domain.)
- In Search Console inspect a published canonical URL, request indexing only when useful, and watch Pages/Indexing plus Performance impressions, queries, clicks, CTR and average position.
- In Bing, submit the same sitemap, confirm IndexNow receipts, and watch Search Performance, Index Explorer and any AI/citation reporting that is actually enabled for the property. Availability varies by account and region.
- The workflow is publish → notify → index → measure → improve a proven page → measure again. It does not generate content automatically from console data.

## Analítica privada

Todas las páginas cargan `/assets/analytics.js` con `defer`. El script espera a que el navegador quede inactivo, respeta `Do Not Track` y envía solamente la ruta visitada y el dominio de referencia. No usa cookies, `localStorage`, fingerprinting, IP almacenada ni identificadores persistentes.

La función `netlify/functions/analytics.mjs` conserva un contador agregado en Netlify Blobs: visitas totales, últimos 31 días, páginas más vistas y dominios de referencia. No existe un endpoint público de lectura: cualquier petición `GET` responde `404`.

El propietario puede consultar el resumen desde una sesión autenticada de Netlify:

```powershell
npx netlify blobs:get stacksignal-private-analytics summary-v1
```

El plan Free de Netlify tiene límite rígido de uso: no genera cargos automáticos, aunque el proyecto puede pausarse si agota la cuota mensual.

## Docker

```powershell
docker build --build-arg BASE_URL=https://tu-dominio.com -t stacksignal .
docker run --rm -p 8080:8080 stacksignal
```

Para producción, construir y desplegar nuevamente cuando cambie el contenido. Persistir `data/state.sqlite3` en el proceso editorial o CI para conservar la cola incremental de IndexNow. El contenedor de Nginx sólo sirve los archivos ya generados.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican el tag, las declaraciones de afiliación, `noindex` para borradores, exclusión del sitemap, cola IndexNow y expansión de más de mil briefs.

## Referencias operativas

- [Google: contenido generado con IA](https://developers.google.com/search/docs/fundamentals/using-gen-ai-content)
- [Google: funciones de IA y tu sitio](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
- [Amazon Associates Operating Agreement](https://affiliate-program.amazon.com/help/operating/agreement)
- [Amazon: divulgación de afiliación](https://affiliate-program.amazon.com/help/node/topic/GHQNZAU6669EZS98)
- [IndexNow: documentación](https://www.indexnow.org/documentation)
- [IndexNow: preguntas frecuentes](https://www.indexnow.org/faq)
