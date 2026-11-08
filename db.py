"""Capa de base de datos del chat.

- Si existe la variable de entorno DATABASE_URL se usa PostgreSQL (Render).
- Si no existe, se usa SQLite en un archivo local (chat.db) para desarrollo.

Tablas:
    usuarios (id, usuario, password_hash, creado_en)
    mensajes (id, usuario_id, texto, creado_en, editado)

Operaciones CRUD sobre los mensajes:
    Create -> crear_mensaje()
    Read   -> listar_mensajes() / obtener_mensaje()
    Update -> editar_mensaje()
    Delete -> borrar_mensaje()
"""
import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL")
USAR_POSTGRES = bool(DATABASE_URL)
RUTA_SQLITE = os.environ.get("SQLITE_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "chat.db"
)

if USAR_POSTGRES:
    import psycopg2

# Errores que significan "ese registro ya existe" (usuario repetido)
ERRORES_DUPLICADO = (sqlite3.IntegrityError,)
if USAR_POSTGRES:
    ERRORES_DUPLICADO += (psycopg2.IntegrityError,)


# ------------------------------------------------------------------
# Conexión
# ------------------------------------------------------------------
@contextmanager
def conexion():
    """Abre una conexión, confirma los cambios al salir y la cierra."""
    if USAR_POSTGRES:
        con = psycopg2.connect(DATABASE_URL)
    else:
        con = sqlite3.connect(RUTA_SQLITE, timeout=10)
        con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _sql(sql):
    """SQLite usa ? como marcador y PostgreSQL usa %s."""
    return sql.replace("?", "%s") if USAR_POSTGRES else sql


def _insertar(con, sql, params):
    """Inserta una fila y devuelve su id."""
    cur = con.cursor()
    if USAR_POSTGRES:
        cur.execute(_sql(sql) + " RETURNING id", params)
        return cur.fetchone()[0]
    cur.execute(sql, params)
    return cur.lastrowid


def _iso(valor):
    """Devuelve la fecha en formato ISO UTC (el navegador la pasa a hora local)."""
    if hasattr(valor, "strftime"):  # PostgreSQL devuelve un datetime
        return valor.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(valor).replace(" ", "T") + "Z"  # SQLite devuelve texto


# ------------------------------------------------------------------
# Creación de tablas
# ------------------------------------------------------------------
def iniciar():
    """Crea las tablas si todavía no existen."""
    with conexion() as con:
        cur = con.cursor()
        if USAR_POSTGRES:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    usuario VARCHAR(20) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    creado_en TIMESTAMP NOT NULL
                        DEFAULT (NOW() AT TIME ZONE 'UTC')
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS mensajes (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL
                        REFERENCES usuarios(id) ON DELETE CASCADE,
                    texto TEXT NOT NULL,
                    creado_en TIMESTAMP NOT NULL
                        DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    editado INTEGER NOT NULL DEFAULT 0
                )"""
            )
        else:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS mensajes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL
                        REFERENCES usuarios(id) ON DELETE CASCADE,
                    texto TEXT NOT NULL,
                    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    editado INTEGER NOT NULL DEFAULT 0
                )"""
            )


# ------------------------------------------------------------------
# Usuarios
# ------------------------------------------------------------------
def crear_usuario(usuario, password_hash):
    """CREATE: guarda un usuario. Devuelve su id, o None si ya existe."""
    try:
        with conexion() as con:
            return _insertar(
                con,
                "INSERT INTO usuarios (usuario, password_hash) VALUES (?, ?)",
                (usuario, password_hash),
            )
    except ERRORES_DUPLICADO:
        return None


def obtener_usuario(usuario):
    """READ: busca un usuario por nombre. Devuelve un diccionario o None."""
    with conexion() as con:
        cur = con.cursor()
        cur.execute(
            _sql("SELECT id, usuario, password_hash FROM usuarios WHERE usuario = ?"),
            (usuario,),
        )
        fila = cur.fetchone()
    if fila is None:
        return None
    return {"id": fila[0], "usuario": fila[1], "password_hash": fila[2]}


# ------------------------------------------------------------------
# Mensajes
# ------------------------------------------------------------------
_SELECT_MENSAJE = """
    SELECT m.id, m.usuario_id, u.usuario, m.texto, m.creado_en, m.editado
    FROM mensajes m
    JOIN usuarios u ON u.id = m.usuario_id
"""


def _a_diccionario(fila):
    return {
        "id": fila[0],
        "usuario_id": fila[1],
        "usuario": fila[2],
        "texto": fila[3],
        "fecha": _iso(fila[4]),
        "editado": bool(fila[5]),
    }


def _buscar_mensaje(con, id_mensaje):
    cur = con.cursor()
    cur.execute(_sql(_SELECT_MENSAJE + " WHERE m.id = ?"), (id_mensaje,))
    fila = cur.fetchone()
    return _a_diccionario(fila) if fila else None


def crear_mensaje(usuario_id, texto):
    """CREATE: guarda un mensaje y lo devuelve completo."""
    with conexion() as con:
        nuevo_id = _insertar(
            con,
            "INSERT INTO mensajes (usuario_id, texto) VALUES (?, ?)",
            (usuario_id, texto),
        )
        return _buscar_mensaje(con, nuevo_id)


def obtener_mensaje(id_mensaje):
    """READ: devuelve un mensaje por su id (o None)."""
    with conexion() as con:
        return _buscar_mensaje(con, id_mensaje)


def listar_mensajes(limite=50):
    """READ: devuelve los últimos mensajes, del más antiguo al más nuevo."""
    with conexion() as con:
        cur = con.cursor()
        cur.execute(
            _sql(_SELECT_MENSAJE + " ORDER BY m.id DESC LIMIT ?"), (limite,)
        )
        filas = cur.fetchall()
    return [_a_diccionario(f) for f in reversed(filas)]


def editar_mensaje(id_mensaje, usuario_id, texto):
    """UPDATE: cambia el texto, solo si el mensaje es del usuario."""
    with conexion() as con:
        cur = con.cursor()
        cur.execute(
            _sql(
                "UPDATE mensajes SET texto = ?, editado = 1 "
                "WHERE id = ? AND usuario_id = ?"
            ),
            (texto, id_mensaje, usuario_id),
        )
        return cur.rowcount > 0


def borrar_mensaje(id_mensaje, usuario_id):
    """DELETE: elimina el mensaje, solo si es del usuario."""
    with conexion() as con:
        cur = con.cursor()
        cur.execute(
            _sql("DELETE FROM mensajes WHERE id = ? AND usuario_id = ?"),
            (id_mensaje, usuario_id),
        )
        return cur.rowcount > 0
