"""Chat en tiempo real con Flask y Flask-SocketIO.

Variables de entorno:
    SECRET_KEY    clave para firmar las sesiones (obligatoria en producción)
    DATABASE_URL  URL de PostgreSQL (si falta, se usa SQLite local)
    PORT          puerto (solo para ejecución local; Render lo gestiona solo)
    FLASK_DEBUG   "1" activa el modo depuración (solo en desarrollo)
"""
import hmac
import os
import re
import secrets
import threading
from functools import wraps

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash, generate_password_hash

import db

# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------
USUARIO_VALIDO = re.compile(r"^[A-Za-z0-9_]{3,20}$")
PASSWORD_MIN = 6
PASSWORD_MAX = 128
MENSAJE_MAX = 500

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Render define la variable RENDER; allí la cookie solo viaja por HTTPS
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

# Modo "threading": funciona con gunicorn --threads y simple-websocket
socketio = SocketIO(app, async_mode="threading")

db.iniciar()

conectados = {}  # sid del socket -> nombre de usuario
bloqueo = threading.Lock()


# ------------------------------------------------------------------
# Seguridad: CSRF, cabeceras y sesión
# ------------------------------------------------------------------
def token_csrf():
    """Devuelve el token CSRF de la sesión (lo crea si no existe)."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def csrf_valido():
    enviado = request.form.get("csrf", "")
    guardado = session.get("csrf", "")
    return bool(guardado) and hmac.compare_digest(
        enviado.encode(), guardado.encode()
    )


app.jinja_env.globals["csrf_token"] = token_csrf


@app.after_request
def cabeceras_seguridad(respuesta):
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    return respuesta


def login_requerido(funcion):
    @wraps(funcion)
    def interno(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)

    return interno


# ------------------------------------------------------------------
# Rutas HTTP
# ------------------------------------------------------------------
@app.route("/")
def inicio():
    if "usuario_id" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("registro.html")

    def error(mensaje, usuario=""):
        return render_template("registro.html", error=mensaje, usuario=usuario), 400

    if not csrf_valido():
        return error("La sesión expiró. Intenta de nuevo.")

    usuario = request.form.get("usuario", "").strip().lower()
    password = request.form.get("password", "")
    confirmar = request.form.get("confirmar", "")

    if not USUARIO_VALIDO.match(usuario):
        return error(
            "El usuario debe tener de 3 a 20 caracteres: letras, números o _.",
            usuario,
        )
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return error(
            f"La contraseña debe tener entre {PASSWORD_MIN} y {PASSWORD_MAX} caracteres.",
            usuario,
        )
    if password != confirmar:
        return error("Las contraseñas no coinciden.", usuario)

    if db.crear_usuario(usuario, generate_password_hash(password)) is None:
        return error("Ese usuario ya existe. Elige otro.", usuario)

    return redirect(url_for("login", registrado=1))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "usuario_id" in session:
        return redirect(url_for("chat"))

    if request.method == "GET":
        return render_template("login.html", exito=request.args.get("registrado"))

    if not csrf_valido():
        return (
            render_template("login.html", error="La sesión expiró. Intenta de nuevo."),
            400,
        )

    usuario = request.form.get("usuario", "").strip().lower()
    password = request.form.get("password", "")
    fila = db.obtener_usuario(usuario)

    if fila and check_password_hash(fila["password_hash"], password):
        session.clear()  # sesión nueva al iniciar (evita fijación de sesión)
        session["usuario_id"] = fila["id"]
        session["usuario"] = fila["usuario"]
        return redirect(url_for("chat"))

    return (
        render_template(
            "login.html", error="Usuario o contraseña incorrectos.", usuario=usuario
        ),
        401,
    )


@app.route("/logout", methods=["POST"])
def logout():
    if csrf_valido():
        session.clear()
    return redirect(url_for("login"))


@app.route("/chat")
@login_requerido
def chat():
    return render_template("chat.html", usuario=session["usuario"])


@app.route("/api/mensajes")
def api_mensajes():
    """READ por HTTP: devuelve los últimos mensajes en formato JSON."""
    if "usuario_id" not in session:
        return jsonify({"error": "No autorizado"}), 401
    return jsonify(db.listar_mensajes())


@app.route("/salud")
def salud():
    """Ruta sencilla para comprobar que el servicio está vivo."""
    return "ok"


# ------------------------------------------------------------------
# Socket.IO (tiempo real)
# ------------------------------------------------------------------
def limpiar_texto(valor):
    """Devuelve el texto validado o None si no es válido."""
    if isinstance(valor, dict):
        valor = valor.get("texto", "")
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    if not valor or len(valor) > MENSAJE_MAX:
        return None
    return valor


def a_entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def enviar_usuarios():
    with bloqueo:
        lista = sorted(set(conectados.values()))
    socketio.emit("usuarios", lista)


@socketio.on("connect")
def al_conectar():
    if "usuario_id" not in session:
        return False  # rechaza conexiones sin sesión iniciada
    with bloqueo:
        conectados[request.sid] = session["usuario"]
    emit("historial", db.listar_mensajes())
    enviar_usuarios()


@socketio.on("disconnect")
def al_desconectar(*args):
    with bloqueo:
        conectados.pop(request.sid, None)
    enviar_usuarios()


@socketio.on("enviar_mensaje")
def enviar_mensaje(datos):
    if "usuario_id" not in session:
        return
    texto = limpiar_texto(datos)
    if texto is None:
        emit("error_chat", f"El mensaje debe tener entre 1 y {MENSAJE_MAX} caracteres.")
        return
    mensaje = db.crear_mensaje(session["usuario_id"], texto)
    socketio.emit("nuevo_mensaje", mensaje)


@socketio.on("editar_mensaje")
def editar_mensaje(datos):
    if "usuario_id" not in session or not isinstance(datos, dict):
        return
    id_mensaje = a_entero(datos.get("id"))
    texto = limpiar_texto(datos.get("texto"))
    if id_mensaje is None or texto is None:
        emit("error_chat", "No se pudo editar: datos no válidos.")
        return
    if db.editar_mensaje(id_mensaje, session["usuario_id"], texto):
        socketio.emit("mensaje_editado", {"id": id_mensaje, "texto": texto})
    else:
        emit("error_chat", "Solo puedes editar tus propios mensajes.")


@socketio.on("borrar_mensaje")
def borrar_mensaje(datos):
    if "usuario_id" not in session or not isinstance(datos, dict):
        return
    id_mensaje = a_entero(datos.get("id"))
    if id_mensaje is None:
        return
    if db.borrar_mensaje(id_mensaje, session["usuario_id"]):
        socketio.emit("mensaje_borrado", {"id": id_mensaje})
    else:
        emit("error_chat", "Solo puedes borrar tus propios mensajes.")


# ------------------------------------------------------------------
# Ejecución local
# ------------------------------------------------------------------
if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    print("Chat Socket iniciado en http://0.0.0.0:%d" % puerto)
    socketio.run(app, host="0.0.0.0", port=puerto)