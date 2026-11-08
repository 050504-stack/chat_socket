# Chat Socket

Aplicación web de chat en tiempo real. Los usuarios se registran, inician
sesión y conversan en una sala común. Los mensajes se guardan en una base de
datos, por lo que el historial se conserva aunque se cierre el navegador.

## 1. Funcionalidades

- Registro e inicio de sesión con contraseñas cifradas.
- Chat en tiempo real entre varios usuarios (WebSockets con Socket.IO).
- Historial de los últimos 50 mensajes al entrar.
- Editar y borrar los mensajes propios (los cambios se ven al instante en todos
  los usuarios conectados).
- Lista de usuarios en línea y hora de cada mensaje.
- Diseño adaptable a computador y celular.

## 2. Tecnologías

| Capa | Tecnología |
|---|---|
| Servidor | Python 3.12, Flask, Flask-SocketIO |
| Tiempo real | Socket.IO (WebSocket) |
| Base de datos | PostgreSQL en producción (Render), SQLite en local |
| Servidor de producción | Gunicorn con hilos (`--threads`) y simple-websocket |
| Cliente | HTML, CSS y JavaScript |
| Despliegue | Render (conectado a GitHub) |

## 3. Arquitectura

```
Navegador (HTML + CSS + chat.js)
      |   HTTP: login, registro, páginas
      |   WebSocket (Socket.IO): mensajes en tiempo real
      v
Servidor Flask + Flask-SocketIO (server.py)
      |   funciones de acceso a datos
      v
Capa de base de datos (db.py)  --->  PostgreSQL (Render) / SQLite (local)
```

Flujo de un mensaje:

1. El usuario escribe y `chat.js` envía el evento `enviar_mensaje`.
2. El servidor valida el texto y toma el nombre de usuario de la sesión.
3. `db.crear_mensaje()` guarda el mensaje en la base de datos.
4. El servidor emite `nuevo_mensaje` a todos los clientes conectados.

### Estructura de carpetas

```
chat_socket/
├── server.py          Servidor: rutas HTTP y eventos Socket.IO
├── db.py              Acceso a la base de datos (CRUD)
├── test_chat.py       Pruebas automáticas
├── requirements.txt   Dependencias de Python
├── .python-version    Versión de Python para Render
├── .gitignore         Archivos que no se suben a GitHub
├── README.md          Esta documentación
├── templates/
│   ├── login.html     Inicio de sesión
│   ├── registro.html  Creación de cuenta
│   └── chat.html      Pantalla del chat
└── static/
    ├── style.css      Estilos (diseño adaptable)
    └── chat.js        Lógica del cliente
```

## 4. Base de datos

**usuarios**: `id`, `usuario` (único), `password_hash`, `creado_en`

**mensajes**: `id`, `usuario_id` (→ usuarios), `texto`, `creado_en`, `editado`

Operaciones CRUD sobre los mensajes:

| Operación | Función (db.py) | Evento Socket.IO / ruta |
|---|---|---|
| Create | `crear_mensaje()` | `enviar_mensaje` |
| Read | `listar_mensajes()`, `obtener_mensaje()` | al conectar (`historial`) y `GET /api/mensajes` |
| Update | `editar_mensaje()` | `editar_mensaje` |
| Delete | `borrar_mensaje()` | `borrar_mensaje` |

Los usuarios también se crean (`crear_usuario()`) y se consultan
(`obtener_usuario()`) en el registro y el inicio de sesión.

## 5. Seguridad aplicada

- Contraseñas guardadas con hash (`werkzeug.security`), nunca en texto plano.
- Validación en el servidor de usuario, contraseña y largo de los mensajes.
- Token CSRF en los formularios de registro, login y salida.
- Las rutas y el socket exigen sesión iniciada; sin sesión se rechazan.
- El nombre del autor lo define el servidor con la sesión, no el navegador
  (nadie puede hacerse pasar por otro usuario).
- Solo el autor puede editar o borrar sus mensajes (se comprueba en la
  consulta SQL).
- Consultas SQL con parámetros (protege contra inyección SQL).
- Los mensajes se muestran con `textContent` (protege contra inyección de HTML).
- `SECRET_KEY` y `DATABASE_URL` se leen de variables de entorno, no del código.
- Cookie de sesión `HttpOnly`, `SameSite=Lax` y `Secure` en Render.
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`.
- El modo depuración solo se activa con `FLASK_DEBUG=1` (solo en desarrollo).

## 6. Instalación y ejecución en local

Requisitos: Python 3.12 y Git.

```bash
# 1. Crear y activar el entorno virtual
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Mac / Linux

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar
python server.py
```

Abrir <http://127.0.0.1:5000>, crear una cuenta e iniciar sesión. Sin la
variable `DATABASE_URL` se usa SQLite y se crea el archivo `chat.db`.

Para probar con varios usuarios, abrir una ventana normal y otra de incógnito
(cada una con una cuenta distinta).

### Variables de entorno

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Clave para firmar las sesiones. Obligatoria en producción. |
| `DATABASE_URL` | URL de PostgreSQL. Si falta, se usa SQLite. |
| `FLASK_DEBUG` | `1` activa el modo depuración (solo en local). |
| `PORT` | Puerto local (por defecto 5000). |

## 7. Despliegue en Render

1. **Subir el proyecto a GitHub** (la carpeta `venv` no se sube porque está en
   `.gitignore`):
   ```bash
   git init
   git add .
   git commit -m "Chat Socket"
   git branch -M main
   git remote add origin https://github.com/USUARIO/REPOSITORIO.git
   git push -u origin main
   ```
2. **Crear la base de datos:** en Render, `New` → `PostgreSQL`, plan Free.
   Cuando esté lista, copiar el **Internal Database URL**.
3. **Crear el servicio web:** `New` → `Web Service`, conectar el repositorio y
   configurar:
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn -w 1 --threads 100 server:app`
   - Instance Type: `Free`
4. **Variables de entorno** (sección Environment):
   - `SECRET_KEY` = un texto largo y aleatorio
   - `DATABASE_URL` = el Internal Database URL del paso 2
5. Pulsar **Deploy**. Al terminar, abrir la URL `https://...onrender.com`,
   crear una cuenta y probar el chat.

Se usa `-w 1` (un solo proceso) porque la lista de usuarios conectados se
guarda en memoria; los hilos (`--threads 100`) permiten atender muchos
usuarios a la vez.

## 8. Pruebas

### Pruebas automáticas

El archivo `test_chat.py` ejecuta 39 comprobaciones sobre una base de datos
temporal (no toca los datos reales):

```bash
python test_chat.py
```

Cubre: registro (usuario repetido, símbolos, contraseña corta, contraseñas
distintas, token CSRF inválido), login (clave incorrecta, acceso a `/chat` sin
sesión), chat en tiempo real entre dos usuarios, CRUD de mensajes (otro usuario
no puede editar ni borrar mensajes ajenos), mensajes vacíos o demasiado largos,
datos inválidos y persistencia del historial al reconectar.

### Pruebas manuales (marcar al probar)

- [ ] Dos usuarios en ventanas distintas ven los mensajes del otro al instante.
- [ ] Editar y borrar un mensaje se refleja en la otra ventana.
- [ ] Se ve bien en un celular (o con el modo móvil del navegador).
- [ ] Funciona en Chrome y en otro navegador (Firefox o Edge).
- [ ] La URL de Render abre y permite registrarse e iniciar sesión.

## 9. Limitaciones y mejoras futuras

- En el plan gratuito de Render el servicio se apaga tras 15 minutos sin
  tráfico; la primera visita después de ese tiempo puede tardar cerca de un
  minuto en cargar.
- Una sola sala de chat. Se podrían agregar salas y mensajes privados.
- No hay límite de intentos de inicio de sesión ni recuperación de contraseña.
## Despliegue en Producción
Aplicación desplegada y funcional en Render:
https://chat-socket-dilan.onrender.com