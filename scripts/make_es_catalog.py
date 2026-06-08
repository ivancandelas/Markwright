"""One-shot helper: fill translations/es/LC_MESSAGES/messages.po with the Spanish
strings below, preserving msgids/placeholders from messages.pot. Re-run after
`pybabel update` to (re)apply known translations; unknown msgids stay blank.

    .venv/bin/python scripts/make_es_catalog.py

The TRANSLATIONS dict is the source of truth for the Spanish UI. Add an entry
for any new msgid, then run this + `pybabel compile`.
"""
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ES = {
    # --- server / API errors --------------------------------------------
    "source is required": "Se requiere un origen",
    "git command timed out": "El comando git agotó el tiempo de espera",
    "git is not installed or not on PATH": "git no está instalado o no está en el PATH",
    "path is required": "Se requiere una ruta",
    "Cannot remove the active source": "No se puede quitar el origen activo",
    "Not found in recents": "No se encontró en los recientes",
    "file is required": "Se requiere un archivo",
    "not found": "no encontrado",
    "Playwright is not installed. Run: uv pip install playwright":
        "Playwright no está instalado. Ejecuta: uv pip install playwright",
    "Chrome (or Chromium) is required for PDF export but was not found. "
    "Install Google Chrome and try again.":
        "Se requiere Chrome (o Chromium) para exportar a PDF, pero no se encontró. "
        "Instala Google Chrome e inténtalo de nuevo.",
    "Chrome refused to load the page on this port. Restart the viewer on a different --port.":
        "Chrome se negó a cargar la página en este puerto. Reinicia el visor en otro --port.",
    "PDF export timed out — the document may be very large or a diagram failed to load. "
    "See the server logs for details.":
        "La exportación a PDF agotó el tiempo de espera — el documento puede ser muy grande "
        "o un diagrama no se cargó. Consulta los registros del servidor para más detalles.",
    "Could not generate the PDF. See the server logs for details.":
        "No se pudo generar el PDF. Consulta los registros del servidor para más detalles.",
    "Could not generate the DOCX. See the server logs for details.":
        "No se pudo generar el DOCX. Consulta los registros del servidor para más detalles.",
    "Pandoc is not installed. Install it (e.g. `apt install pandoc`) to export to Word.":
        "Pandoc no está instalado. Instálalo (p. ej. `apt install pandoc`) para exportar a Word.",
    "Name is required": "El nombre es obligatorio",
    "Unsupported logo format: %(ext)s": "Formato de logo no soportado: %(ext)s",
    "(no extension)": "(sin extensión)",
    "The logo exceeds the 2 MB limit": "El logo supera el límite de 2 MB",
    "Unsupported image format: %(ext)s": "Formato de imagen no soportado: %(ext)s",
    "The cover image exceeds the 2 MB limit": "La imagen de portada supera el límite de 2 MB",
    "Not found": "No encontrado",
    # --- frontmatter toggle --------------------------------------------
    "This document has no frontmatter": "Este documento no tiene frontmatter",
    "Frontmatter hidden — click to show": "Frontmatter oculto — haz clic para mostrar",
    "Hide frontmatter panel": "Ocultar el panel de frontmatter",
    # --- mermaid / source toggles --------------------------------------
    "Show source": "Ver código",
    "Toggle diagram source": "Alternar el código del diagrama",
    "Show diagram": "Ver diagrama",
    # --- font size ------------------------------------------------------
    "Font size (default)": "Tamaño de fuente (predeterminado)",
    "Reset font size to %(size)s": "Restablecer el tamaño de fuente a %(size)s",
    "System default": "Predeterminado del sistema",
    # --- copy button ----------------------------------------------------
    "Copy": "Copiar",
    "Copy code to clipboard": "Copiar el código al portapapeles",
    "Copied!": "¡Copiado!",
    "Failed": "Error",
    # --- tree collapse --------------------------------------------------
    "Expand all": "Expandir todo",
    "Collapse all": "Contraer todo",
    "Expand all folders": "Expandir todas las carpetas",
    "Collapse all folders": "Contraer todas las carpetas",
    # --- source picker / status ----------------------------------------
    "Loading…": "Cargando…",
    "Failed (%(status)s)": "Error (%(status)s)",
    "Loaded — reloading…": "Cargado — recargando…",
    "Removing…": "Quitando…",
    "Removed — reloading…": "Quitado — recargando…",
    "View rendered": "Ver renderizado",
    "View source": "Ver código fuente",
    # --- reading aids ---------------------------------------------------
    "%(words)s words · ~%(min)s min read": "%(words)s palabras · ~%(min)s min de lectura",
    "Copy link to this section": "Copiar enlace a esta sección",
    "Back to top": "Volver arriba",
    "Focus reading (F)": "Lectura enfocada (F)",
    "Focus reading": "Lectura enfocada",
    "Exit focus reading (Esc)": "Salir de la lectura enfocada (Esc)",
    "Exit focus reading": "Salir de la lectura enfocada",
    "~%(min)s min left": "~%(min)s min restantes",
    "Almost done": "Casi terminado",
    # --- edit mode ------------------------------------------------------
    "Edit": "Editar",
    "Edit source": "Editar el código fuente",
    "Stop editing": "Dejar de editar",
    "Save": "Guardar",
    "Save (Ctrl+S)": "Guardar (Ctrl+S)",
    "Unsaved changes": "Cambios sin guardar",
    "Cancel": "Cancelar",
    "Saving…": "Guardando…",
    "Saved": "Guardado",
    "Saved — reloading…": "Guardado — recargando…",
    "This source is read-only": "Este origen es de solo lectura",
    "file and content are required": "se requieren el archivo y el contenido",
    "Bold (Ctrl+B)": "Negrita (Ctrl+B)",
    "Italic (Ctrl+I)": "Cursiva (Ctrl+I)",
    "Inline code": "Código en línea",
    "Insert link (Ctrl+K)": "Insertar enlace (Ctrl+K)",
    "Preview": "Vista previa",
    "Sync scroll": "Sincronizar desplazamiento",
    "Keep editor and preview scroll positions aligned": "Mantener alineadas las posiciones de desplazamiento del editor y la vista previa",
    "Toggle fullscreen": "Pantalla completa",
    "%(w)s words · %(c)s chars": "%(w)s palabras · %(c)s caracteres",
    "Discard unsaved changes?": "¿Descartar los cambios sin guardar?",
    "An unsaved draft from %(when)s was found. Restore it?":
        "Se encontró un borrador sin guardar de %(when)s. ¿Restaurarlo?",
    "Uploading image…": "Subiendo imagen…",
    "No image provided": "No se proporcionó ninguna imagen",
    "The image exceeds the 10 MB limit": "La imagen supera el límite de 10 MB",
    # --- file actions (new / rename / delete) ---------------------------
    "File actions": "Acciones de archivo",
    "New file…": "Nuevo archivo…",
    "Rename…": "Renombrar…",
    "Delete…": "Eliminar…",
    "New file": "Nuevo archivo",
    "Rename file": "Renombrar archivo",
    "Create": "Crear",
    "Rename": "Renombrar",
    "Delete": "Eliminar",
    "Working…": "Procesando…",
    "notes.md or docs/notes.md": "notas.md o docs/notas.md",
    "Delete \"%(name)s\"? This cannot be undone.":
        "¿Eliminar «%(name)s»? Esta acción no se puede deshacer.",
    "A file name is required": "Se requiere un nombre de archivo",
    "Use a .md or .rst file extension": "Usa una extensión de archivo .md o .rst",
    "A file with that name already exists": "Ya existe un archivo con ese nombre",
    # --- export ---------------------------------------------------------
    "Generating…": "Generando…",
    "Error %(status)s": "Error %(status)s",
    "Done": "Listo",
    # --- preset manager -------------------------------------------------
    "No presets yet.": "Aún no hay ajustes.",
    "Saving…": "Guardando…",
    "Saved": "Guardado",
    "Duplicating…": "Duplicando…",
    "Duplicated": "Duplicado",
    "Delete preset \"%(name)s\"?": "¿Eliminar el ajuste «%(name)s»?",
    "Remove \"%(label)s\" from recents and delete the cached clone?":
        "¿Quitar «%(label)s» de los recientes y eliminar el clon en caché?",
    # --- appearance / settings -----------------------------------------
    "Appearance settings": "Ajustes de apariencia",
    "Hide sidebar": "Ocultar la barra lateral",
    "Appearance": "Apariencia",
    "Language": "Idioma",
    "Theme": "Tema",
    "Light": "Claro",
    "Dark": "Oscuro",
    "Sepia": "Sepia",
    "Font": "Fuente",
    "Diagram theme": "Tema del diagrama",
    "Match page": "Coincidir con la página",
    "Auto (match page)": "Automático (coincidir con la página)",
    "Page palettes": "Paletas de la página",
    "Mermaid built-in": "Integrados de Mermaid",
    "Default": "Predeterminado",
    "Neutral": "Neutro",
    "Forest": "Bosque",
    "Base": "Base",
    "Content width": "Ancho del contenido",
    "Change content width": "Cambiar el ancho del contenido",
    "Narrow": "Estrecho",
    "Wide": "Ancho",
    "Full": "Completo",
    "Font size": "Tamaño de fuente",
    "Content font size": "Tamaño de fuente del contenido",
    "Decrease font size": "Reducir el tamaño de fuente",
    "Reset font size": "Restablecer el tamaño de fuente",
    "Increase font size": "Aumentar el tamaño de fuente",
    # --- source picker --------------------------------------------------
    "Source": "Origen",
    "/path/to/folder or https://github.com/user/repo":
        "/ruta/a/la/carpeta o https://github.com/usuario/repo",
    "Open": "Abrir",
    "Recent": "Recientes",
    "Remove from recents": "Quitar de los recientes",
    "(deletes cached clone)": "(elimina el clon en caché)",
    "Remove %(label)s from recents": "Quitar %(label)s de los recientes",
    # --- bookmarks ------------------------------------------------------
    "Bookmarks": "Marcadores",
    "Bookmarked": "Marcados",
    "Bookmarked files": "Archivos marcados",
    "Bookmark this file": "Marcar este archivo",
    "+ Bookmark this spot": "+ Marcar esta posición",
    "✓ Bookmarked": "✓ Marcado",
    "Tap to bookmark this spot · hold to open the list":
        "Toca para marcar esta posición · mantén pulsado para ver la lista",
    "No saved positions on this page yet.":
        "Aún no hay posiciones guardadas en esta página.",
    "Remove bookmark": "Quitar marcador",
    "★ Remove file bookmark": "★ Quitar marcador del archivo",
    "☆ Bookmark this file": "☆ Marcar este archivo",
    "Position at %(px)spx": "Posición en %(px)spx",
    "(untitled)": "(sin título)",
    "Remove": "Quitar",
    # --- file tree ------------------------------------------------------
    "Search markdown files": "Buscar archivos markdown",
    "Filter files...": "Filtrar archivos...",
    "Sort folders and files": "Ordenar carpetas y archivos",
    "Sort order": "Criterio de orden",
    "Name (A→Z)": "Nombre (A→Z)",
    "Name (Z→A)": "Nombre (Z→A)",
    "Newest first": "Más recientes primero",
    "Oldest first": "Más antiguos primero",
    "Markdown files": "Archivos markdown",
    "No markdown files found.": "No se encontraron archivos markdown.",
    "Show sidebar": "Mostrar la barra lateral",
    # --- document header ------------------------------------------------
    "Current file": "Archivo actual",
    "No markdown file selected": "Ningún archivo markdown seleccionado",
    "Root: %(dir)s": "Raíz: %(dir)s",
    "Toggle source view": "Alternar la vista de código",
    "Show/hide frontmatter panel": "Mostrar/ocultar el panel de frontmatter",
    "Toggle frontmatter panel": "Alternar el panel de frontmatter",
    "Export as PDF": "Exportar como PDF",
    # --- export popover -------------------------------------------------
    "Export PDF": "Exportar PDF",
    "Preset": "Ajuste",
    "Custom (no preset)": "Personalizado (sin ajuste)",
    "Manage presets": "Gestionar ajustes",
    "Header": "Encabezado",
    "Left": "Izquierda",
    "Center": "Centro",
    "Right": "Derecha",
    "Footer": "Pie de página",
    "Include contents page": "Incluir página de contenido",
    "Include cover page": "Incluir página de portada",
    "(needs a preset)": "(requiere un ajuste)",
    "Include frontmatter panel": "Incluir el panel de frontmatter",
    "Download PDF": "Descargar PDF",
    "Word (.docx)": "Word (.docx)",
    "Export to Word (.docx) — uses the preset’s contents-page option; "
    "header/footer, cover and margins are PDF-only":
        "Exportar a Word (.docx) — usa la opción de página de contenido del ajuste; "
        "el encabezado/pie, la portada y los márgenes son solo para PDF",
    "Table of contents": "Tabla de contenido",
    "Contents": "Contenido",
    "Add a <code>.md</code> file to this directory, then refresh the browser.":
        "Añade un archivo <code>.md</code> a este directorio y luego recarga el navegador.",
    "On this page": "En esta página",
    "Hide table of contents": "Ocultar la tabla de contenido",
    "Show table of contents": "Mostrar la tabla de contenido",
    # --- preset modal ---------------------------------------------------
    "PDF presets": "Ajustes de PDF",
    "Close (Esc)": "Cerrar (Esc)",
    "Close": "Cerrar",
    "+ New preset": "+ Nuevo ajuste",
    "Name": "Nombre",
    "Download file name": "Nombre del archivo descargado",
    "Logo position": "Posición del logo",
    "Logo image": "Imagen del logo",
    "Logo preview": "Vista previa del logo",
    "Remove logo": "Quitar logo",
    "Page size": "Tamaño de página",
    "Tabloid / Ledger (11×17)": "Tabloide / Ledger (11×17)",
    "Orientation": "Orientación",
    "Portrait": "Vertical",
    "Landscape": "Horizontal",
    "Body font": "Fuente del cuerpo",
    "Body font size (percent)": "Tamaño de fuente del cuerpo (porcentaje)",
    "Include contents page (clickable, before the document)":
        "Incluir página de contenido (con enlaces, antes del documento)",
    "Include frontmatter panel in the PDF body":
        "Incluir el panel de frontmatter en el cuerpo del PDF",
    "Cover page": "Página de portada",
    "Add a cover page": "Añadir una página de portada",
    "Title": "Título",
    "Subtitle": "Subtítulo",
    "e.g. Technical Specification": "p. ej. Especificación técnica",
    "Metadata rows (one <code>Label: value</code> per line)":
        "Filas de metadatos (un <code>Etiqueta: valor</code> por línea)",
    "Footer line": "Línea de pie de página",
    "Cover image": "Imagen de portada",
    "None": "Ninguna",
    "Use preset logo": "Usar el logo del ajuste",
    "Upload an image": "Subir una imagen",
    "Blank page after cover": "Página en blanco tras la portada",
    "Image file": "Archivo de imagen",
    "Cover image preview": "Vista previa de la imagen de portada",
    "Remove cover image": "Quitar la imagen de portada",
    "Default values (fallback)": "Valores predeterminados (reserva)",
    "Fallback values (one <code>key: value</code> per line)":
        "Valores de reserva (un <code>clave: valor</code> por línea)",
    "Use these defaults when the document has no frontmatter (or is missing a key)":
        "Usar estos valores cuando el documento no tiene frontmatter (o le falta una clave)",
    "Margins (mm)": "Márgenes (mm)",
    "Top": "Superior",
    "Bottom": "Inferior",
    "Save preset": "Guardar ajuste",
    "Duplicate": "Duplicar",
    "Delete": "Eliminar",
    # --- diagram overlay ------------------------------------------------
    "Diagram viewer": "Visor de diagramas",
    "Zoom controls": "Controles de zoom",
    "Zoom": "Zoom",
    "Zoom out": "Alejar",
    "Zoom level": "Nivel de zoom",
    "Zoom in": "Acercar",
    "Reset zoom (0)": "Restablecer zoom (0)",
    "Reset zoom": "Restablecer zoom",
    "Backdrop opacity": "Opacidad del fondo",
    "Opacity": "Opacidad",
    "Decrease backdrop opacity": "Reducir la opacidad del fondo",
    "Increase backdrop opacity": "Aumentar la opacidad del fondo",
    # --- keyboard shortcuts help ----------------------------------------
    "Keyboard shortcuts (?)": "Atajos de teclado (?)",
    "Keyboard shortcuts": "Atajos de teclado",
    "Show this help": "Mostrar esta ayuda",
    "Search files": "Buscar archivos",
    "Toggle sidebar": "Mostrar/ocultar la barra lateral",
    "Toggle focus reading mode": "Activar/desactivar el modo de lectura enfocada",
    "Close dialogs / exit modes": "Cerrar diálogos / salir de los modos",
    "General": "General",
    "Document": "Documento",
    "Edit document (when editable)": "Editar el documento (cuando es editable)",
    "Focus reading mode": "Modo de lectura enfocada",
    "Page down": "Avanzar una página",
    "Page up": "Retroceder una página",
    "Page down / up": "Avanzar / retroceder una página",
    "Scroll down / up": "Desplazar hacia abajo / arriba",
    "Exit focus mode": "Salir del modo enfocado",
    "Editor": "Editor",
    "Exit editor": "Salir del editor",
    "Bold": "Negrita",
    "Italic": "Cursiva",
    "Insert link": "Insertar enlace",
    "Find": "Buscar",
    "Find next": "Buscar siguiente",
    "Find previous": "Buscar anterior",
    "Zoom in / out": "Acercar / alejar",
}

po_path = Path("translations/es/LC_MESSAGES/messages.po")
with po_path.open("rb") as fh:
    catalog = read_po(fh)

catalog.locale = "es"
applied = missing = 0
for message in catalog:
    if not message.id:
        continue
    translation = ES.get(message.id)
    if translation is not None:
        message.string = translation
        # `pybabel update` flags a freshly fuzzy-matched entry `#, fuzzy`, and
        # `pybabel compile` excludes fuzzy entries from the .mo (so they fall
        # back to English). The ES dict is authoritative, so clear the flag.
        message.flags.discard("fuzzy")
        applied += 1
    elif not message.string:
        missing += 1

with po_path.open("wb") as fh:
    write_po(fh, catalog, width=0)

print(f"Applied {applied} translations; {missing} msgids left untranslated.")
