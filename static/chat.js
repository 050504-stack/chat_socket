// Cliente del chat: se comunica con el servidor mediante Socket.IO.

const socket = io();

const usuarioActual = document.body.dataset.usuario;
const contenedor = document.getElementById("mensajes");
const formulario = document.getElementById("formulario");
const campo = document.getElementById("mensaje");
const estado = document.getElementById("estado");
const listaUsuarios = document.getElementById("usuarios");


// ---------- Utilidades ----------

function formatearHora(fechaIso) {
    const fecha = new Date(fechaIso);
    return fecha.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function bajarScroll() {
    contenedor.scrollTop = contenedor.scrollHeight;
}

function crearBoton(texto, titulo, accion) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.textContent = texto;
    boton.title = titulo;
    boton.addEventListener("click", accion);
    return boton;
}

// textContent evita que un mensaje pueda inyectar HTML en la página
function crearMensaje(m) {
    const div = document.createElement("div");
    div.className = "mensaje" + (m.usuario === usuarioActual ? " propio" : "");
    div.dataset.id = m.id;

    const cabecera = document.createElement("div");
    cabecera.className = "mensaje-cabecera";

    const autor = document.createElement("strong");
    autor.textContent = m.usuario;

    const hora = document.createElement("span");
    hora.className = "hora";
    hora.textContent = formatearHora(m.fecha);

    cabecera.append(autor, hora);

    const texto = document.createElement("p");
    texto.className = "texto";
    texto.textContent = m.texto;

    const marca = document.createElement("span");
    marca.className = "editado";
    marca.textContent = m.editado ? "(editado)" : "";

    div.append(cabecera, texto, marca);

    // Solo el autor puede editar o borrar su mensaje
    if (m.usuario === usuarioActual) {
        const acciones = document.createElement("div");
        acciones.className = "acciones";

        acciones.append(
            crearBoton("✏️", "Editar mensaje", function () {
                const nuevo = prompt("Editar mensaje:", texto.textContent);
                if (nuevo === null) {
                    return;
                }
                socket.emit("editar_mensaje", { id: m.id, texto: nuevo });
            }),
            crearBoton("🗑️", "Borrar mensaje", function () {
                if (confirm("¿Borrar este mensaje?")) {
                    socket.emit("borrar_mensaje", { id: m.id });
                }
            })
        );

        div.append(acciones);
    }

    return div;
}

function buscarMensaje(id) {
    return contenedor.querySelector('[data-id="' + id + '"]');
}


// ---------- Eventos del servidor ----------

socket.on("connect", function () {
    estado.textContent = "🟢 Conectado";
});

socket.on("disconnect", function () {
    estado.textContent = "🔴 Desconectado";
});

socket.on("connect_error", function () {
    estado.textContent = "🔴 Sin conexión";
});

socket.on("historial", function (lista) {
    contenedor.replaceChildren(...lista.map(crearMensaje));
    bajarScroll();
});

socket.on("nuevo_mensaje", function (mensaje) {
    contenedor.appendChild(crearMensaje(mensaje));
    bajarScroll();
});

socket.on("mensaje_editado", function (datos) {
    const div = buscarMensaje(datos.id);
    if (div) {
        div.querySelector(".texto").textContent = datos.texto;
        div.querySelector(".editado").textContent = "(editado)";
    }
});

socket.on("mensaje_borrado", function (datos) {
    const div = buscarMensaje(datos.id);
    if (div) {
        div.remove();
    }
});

socket.on("usuarios", function (lista) {
    listaUsuarios.textContent = lista.join(", ");
});

socket.on("error_chat", function (texto) {
    alert(texto);
});


// ---------- Enviar mensaje ----------

formulario.addEventListener("submit", function (evento) {
    evento.preventDefault();

    const texto = campo.value.trim();
    if (texto === "") {
        return;
    }

    socket.emit("enviar_mensaje", { texto: texto });
    campo.value = "";
    campo.focus();
});
