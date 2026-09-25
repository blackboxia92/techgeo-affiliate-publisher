# Publicar StackSignal con GitHub y Netlify

Esta guía usa el repositorio `blackboxia92/techgeo-affiliate-publisher` y el plan Free de Netlify.

## 1. Crear el repositorio vacío

1. Abrir https://github.com/new.
2. En **Repository name**, escribir `techgeo-affiliate-publisher`.
3. Elegir **Public**.
4. Dejar sin marcar **Add a README**, **Add .gitignore** y **Choose a license**.
5. Pulsar **Create repository**.

## 2. Subir la carpeta local

Abrir PowerShell y ejecutar, una línea por vez:

```powershell
cd "C:\Users\conta\Documents\Codex\2026-09-23\ejecut-k02-keigoreply-en-poe-de\outputs\techgeo-affiliate-publisher"
git init
git branch -M main
git add .
git status --short
git commit -m "Initial StackSignal publisher"
git remote add origin https://github.com/blackboxia92/techgeo-affiliate-publisher.git
git push -u origin main
```

Si Git solicita autenticación, elegir **Sign in with your browser**, autorizar GitHub y volver a PowerShell.

## 3. Conectar Netlify

1. Abrir https://app.netlify.com/ y entrar con GitHub.
2. Elegir **Add new project** > **Import an existing project**.
3. Elegir **GitHub** y autorizar el repositorio si lo solicita.
4. Seleccionar `techgeo-affiliate-publisher`.
5. Confirmar que **Publish directory** diga `dist`. El archivo `netlify.toml` completa el resto.
6. Pulsar **Deploy site** o **Publish**.
7. Esperar hasta ver **Published** o **Production deploy: Published**.

## 4. Hacerlo público y elegir el dominio gratuito

1. Si aparece **Private**, pulsar **Make public**.
2. En el panel del proyecto, elegir **Customize** > **Manage project name and cover image**.
3. Probar el nombre `stacksignal-tech`; si ya está ocupado, usar `stacksignal-tech-92`.
4. Guardar. La dirección será `https://stacksignal-tech.netlify.app` o la variante elegida.
5. Ir a **Deploys** > **Trigger deploy** > **Deploy project without cache** para regenerar las URLs canónicas con el nombre definitivo.

## 5. Verificación

Abrir la dirección pública y comprobar:

- La portada carga.
- `/sitemap.xml` muestra XML.
- `/robots.txt` muestra texto.
- `/guides/postgresql-vs-sqlite-backend/` muestra la comparación.

## Actualizaciones futuras

Después de modificar contenido, ejecutar:

```powershell
git add .
git commit -m "Update guides"
git push
```

Netlify reconstruirá y publicará automáticamente.
