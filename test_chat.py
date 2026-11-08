"""Pruebas automáticas del chat. Ejecutar con:  python test_chat.py"""
import os
import re
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["SQLITE_PATH"] = os.path.join(tmp, "prueba.db")
os.environ["SECRET_KEY"] = "clave-de-prueba"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import server  # noqa: E402

app, socketio = server.app, server.socketio
resultados = []


def comprobar(nombre, condicion):
    resultados.append((nombre, bool(condicion)))
    print(("OK   " if condicion else "FALLA"), nombre)


def token(cliente, ruta):
    html = cliente.get(ruta).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def registrar(cliente, usuario, password, confirmar=None, csrf=None):
    return cliente.post("/registro", data={
        "csrf": csrf or token(cliente, "/registro"),
        "usuario": usuario, "password": password,
        "confirmar": confirmar if confirmar is not None else password,
    })


def entrar(cliente, usuario, password, csrf=None):
    return cliente.post("/login", data={
        "csrf": csrf or token(cliente, "/login"),
        "usuario": usuario, "password": password,
    })


# ---------------- Páginas y protección ----------------
anon = app.test_client()
comprobar("GET /login responde 200", anon.get("/login").status_code == 200)
comprobar("GET /registro responde 200", anon.get("/registro").status_code == 200)
comprobar("/chat sin sesión redirige al login",
          anon.get("/chat").status_code == 302 and "/login" in anon.get("/chat").headers["Location"])
comprobar("/api/mensajes sin sesión da 401", anon.get("/api/mensajes").status_code == 401)
comprobar("/salud responde ok", anon.get("/salud").get_data(as_text=True) == "ok")
comprobar("Cabeceras de seguridad presentes",
          anon.get("/login").headers.get("X-Frame-Options") == "DENY")

# ---------------- Registro ----------------
c1 = app.test_client()
r = registrar(c1, "ana", "secreto1")
comprobar("Registro correcto redirige al login", r.status_code == 302 and "registrado=1" in r.headers["Location"])
comprobar("Usuario repetido es rechazado", registrar(c1, "ana", "otraclave").status_code == 400)
comprobar("Usuario con símbolos es rechazado", registrar(c1, "an a!", "secreto1").status_code == 400)
comprobar("Contraseña corta es rechazada", registrar(c1, "pedro", "123").status_code == 400)
comprobar("Contraseñas distintas son rechazadas", registrar(c1, "pedro", "secreto1", "secreto2").status_code == 400)
comprobar("Registro sin token CSRF es rechazado", registrar(c1, "pedro", "secreto1", csrf="falso").status_code == 400)
comprobar("Se crea el segundo usuario", registrar(c1, "luis", "clave123").status_code == 302)

fila = db.obtener_usuario("ana")
comprobar("La contraseña se guarda cifrada", fila and fila["password_hash"] != "secreto1" and len(fila["password_hash"]) > 30)

# ---------------- Login ----------------
c_ana = app.test_client()
comprobar("Login con clave incorrecta da 401", entrar(c_ana, "ana", "mala").status_code == 401)
comprobar("Login sin CSRF da 400", entrar(c_ana, "ana", "secreto1", csrf="falso").status_code == 400)
r = entrar(c_ana, "ana", "secreto1")
comprobar("Login correcto redirige a /chat", r.status_code == 302 and r.headers["Location"].endswith("/chat"))
comprobar("/chat con sesión responde 200", c_ana.get("/chat").status_code == 200)
comprobar("El nombre sale del servidor (no de la URL)",
          'data-usuario="ana"' in c_ana.get("/chat?usuario=hacker").get_data(as_text=True))

c_luis = app.test_client()
entrar(c_luis, "luis", "clave123")

# ---------------- Socket.IO: sin sesión ----------------
sc_anon = socketio.test_client(app, flask_test_client=anon)
comprobar("Socket sin sesión es rechazado", not sc_anon.is_connected())

# ---------------- Socket.IO: con sesión ----------------
sc_ana = socketio.test_client(app, flask_test_client=c_ana)
sc_luis = socketio.test_client(app, flask_test_client=c_luis)
comprobar("Socket con sesión se conecta", sc_ana.is_connected() and sc_luis.is_connected())

recibidos = sc_ana.get_received()
nombres = [m["name"] for m in recibidos]
comprobar("Al conectar llega el historial", "historial" in nombres)
comprobar("Se informa la lista de usuarios en línea", "usuarios" in nombres)
sc_luis.get_received()

# CREATE
sc_ana.emit("enviar_mensaje", {"texto": "Hola desde Ana"})
ev_ana = {m["name"]: m["args"][0] for m in sc_ana.get_received()}
ev_luis = {m["name"]: m["args"][0] for m in sc_luis.get_received()}
msg = ev_ana.get("nuevo_mensaje")
comprobar("CREATE: el mensaje llega al autor", msg and msg["texto"] == "Hola desde Ana")
comprobar("CREATE: el mensaje llega a otro usuario", ev_luis.get("nuevo_mensaje", {}).get("usuario") == "ana")
comprobar("CREATE: el autor lo pone el servidor", msg["usuario"] == "ana")
id_msg = msg["id"]

sc_ana.emit("enviar_mensaje", {"texto": "   "})
comprobar("Mensaje vacío es rechazado", any(m["name"] == "error_chat" for m in sc_ana.get_received()))
sc_ana.emit("enviar_mensaje", {"texto": "x" * 501})
comprobar("Mensaje demasiado largo es rechazado", any(m["name"] == "error_chat" for m in sc_ana.get_received()))
sc_luis.get_received()

# READ
lista = db.listar_mensajes()
comprobar("READ: el mensaje está en la base de datos", any(m["id"] == id_msg for m in lista))
r = c_ana.get("/api/mensajes")
comprobar("READ: /api/mensajes devuelve JSON", r.status_code == 200 and r.get_json()[-1]["id"] == id_msg)

# UPDATE
sc_luis.emit("editar_mensaje", {"id": id_msg, "texto": "robado"})
comprobar("UPDATE: otro usuario NO puede editar", any(m["name"] == "error_chat" for m in sc_luis.get_received()))
sc_ana.get_received()
sc_ana.emit("editar_mensaje", {"id": id_msg, "texto": "Hola editado"})
ev = {m["name"]: m["args"][0] for m in sc_luis.get_received()}
comprobar("UPDATE: el autor edita y otros lo ven", ev.get("mensaje_editado", {}).get("texto") == "Hola editado")
comprobar("UPDATE: queda marcado como editado", db.obtener_mensaje(id_msg)["editado"] is True)
sc_ana.get_received()

# DELETE
sc_luis.emit("borrar_mensaje", {"id": id_msg})
comprobar("DELETE: otro usuario NO puede borrar", any(m["name"] == "error_chat" for m in sc_luis.get_received()))
sc_ana.get_received()
sc_ana.emit("borrar_mensaje", {"id": id_msg})
ev = {m["name"]: m["args"][0] for m in sc_luis.get_received()}
comprobar("DELETE: el autor borra y otros lo ven", ev.get("mensaje_borrado", {}).get("id") == id_msg)
comprobar("DELETE: ya no existe en la base de datos", db.obtener_mensaje(id_msg) is None)

# Datos raros no rompen el servidor
sc_ana.get_received()
for basura in (None, 5, "texto", [], {"id": "abc"}):
    sc_ana.emit("editar_mensaje", basura)
    sc_ana.emit("borrar_mensaje", basura)
    sc_ana.emit("enviar_mensaje", basura)
comprobar("Datos inválidos no rompen el servidor", sc_ana.is_connected())

# Historial al reconectar
sc_ana.emit("enviar_mensaje", {"texto": "Mensaje guardado"})
sc_ana.disconnect()
sc_nuevo = socketio.test_client(app, flask_test_client=c_ana)
hist = [m for m in sc_nuevo.get_received() if m["name"] == "historial"]
comprobar("El historial persiste al reconectar",
          hist and any(x["texto"] == "Mensaje guardado" for x in hist[0]["args"][0]))

# Salir
c_ana.post("/logout", data={"csrf": token(c_ana, "/chat")})
comprobar("Logout cierra la sesión", c_ana.get("/chat").status_code == 302)

# ---------------- Resumen ----------------
fallos = [n for n, ok in resultados if not ok]
print("\n%d pruebas, %d correctas, %d con fallo" % (len(resultados), len(resultados) - len(fallos), len(fallos)))
for n in fallos:
    print("  FALLO:", n)
sys.exit(1 if fallos else 0)
