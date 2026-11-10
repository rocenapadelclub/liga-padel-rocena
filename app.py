import streamlit as st
import gspread
import pandas as pd
import hmac
import hashlib
import secrets as pysecrets
import string
import re
import unicodedata
from gspread.utils import rowcol_to_a1

# =====================================================
# 1. CONFIGURACIÓN
# =====================================================

st.set_page_config(
    page_title="Liga de Pádel Roceña",
    page_icon="🎾",
    layout="centered"
)

st.markdown("""
<style>
    .block-container {
        max-width: 900px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 10px;
        min-height: 42px;
    }
    [data-testid="stMetric"] {
        background: rgba(128,128,128,0.08);
        padding: 10px;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎾 Liga de Pádel Roceña")

USERS_HEADERS = ["Usuario", "Password_hash", "Jugador", "Rol", "Activo"]
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# =====================================================
# 2. FUNCIONES AUXILIARES
# =====================================================

def normalizar(texto):
    return str(texto).strip().lower()


def normalizar_nombre(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def separar_jugadores(texto):
    return [
        nombre.strip()
        for nombre in str(texto).split("/")
        if nombre.strip()
    ]


def es_jugado(valor):
    return normalizar(valor) in ["si", "sí", "yes", "true", "1"]


def columna_letra(numero):
    return rowcol_to_a1(1, numero).replace("1", "")


def hash_password(password):
    salt = pysecrets.token_hex(16)
    iterations = 200000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verificar_password(password, valor_guardado):
    try:
        algoritmo, iteraciones, salt, digest_guardado = valor_guardado.split("$", 3)
        if algoritmo != "pbkdf2_sha256":
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iteraciones)
        ).hex()

        return hmac.compare_digest(digest, digest_guardado)
    except (ValueError, TypeError):
        return False


def generar_password():
    return "".join(pysecrets.choice(PASSWORD_ALPHABET) for _ in range(10))


def generar_usuario(nombre, usuarios_existentes):
    base = unicodedata.normalize("NFKD", str(nombre))
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^a-zA-Z0-9]+", ".", base.lower()).strip(".")
    base = base or "jugador"

    candidato = base
    contador = 2
    existentes = {normalizar(u) for u in usuarios_existentes}

    while candidato in existentes:
        candidato = f"{base}{contador}"
        contador += 1

    return candidato


# =====================================================
# 3. CONEXIÓN GOOGLE SHEETS
# =====================================================

@st.cache_resource
def conectar_google():
    credentials = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credentials)
    spreadsheet = gc.open_by_key(st.secrets["spreadsheet_id"])

    ws_partidos = spreadsheet.worksheet("Partidos")
    ws_jugadores = spreadsheet.worksheet("Jugadores")

    try:
        ws_usuarios = spreadsheet.worksheet("Usuarios")
    except gspread.WorksheetNotFound:
        ws_usuarios = spreadsheet.add_worksheet(
            title="Usuarios",
            rows=100,
            cols=len(USERS_HEADERS)
        )
        ws_usuarios.update(range_name="A1:E1", values=[USERS_HEADERS])

    # Si la pestaña ya existía pero estaba vacía, crea los encabezados.
    if not ws_usuarios.get_all_values():
        ws_usuarios.update(range_name="A1:E1", values=[USERS_HEADERS])

    return ws_partidos, ws_jugadores, ws_usuarios


try:
    ws_partidos, ws_jugadores, ws_usuarios = conectar_google()
except Exception as e:
    st.error("No se ha podido conectar con Google Sheets.")
    st.error(str(e))
    st.stop()


# =====================================================
# 4. LECTURA Y ESCRITURA DE DATOS
# =====================================================

def leer_jugadores():
    valores = ws_jugadores.get_all_records()
    nombres = [
        str(fila.get("Jugador", "")).strip()
        for fila in valores
        if str(fila.get("Jugador", "")).strip()
    ]
    return nombres


def leer_usuarios():
    valores = ws_usuarios.get_all_records()
    usuarios = []

    for fila in valores:
        usuario = str(fila.get("Usuario", "")).strip()
        if not usuario:
            continue

        usuarios.append({
            "usuario": usuario,
            "password_hash": str(fila.get("Password_hash", "")).strip(),
            "jugador": str(fila.get("Jugador", "")).strip(),
            "rol": str(fila.get("Rol", "jugador")).strip().lower(),
            "activo": str(fila.get("Activo", "Si")).strip()
        })

    return usuarios


def leer_datos():
    valores = ws_partidos.get_all_values()

    if not valores:
        raise ValueError("La pestaña Partidos está vacía.")

    headers = [h.strip() for h in valores[0]]
    columnas = {
        normalizar(h): i + 1
        for i, h in enumerate(headers)
    }

    requeridas = [
        "jornada", "partido", "jugadores_a",
        "jugadores_b", "sets_a", "sets_b", "jugado"
    ]

    faltantes = [c for c in requeridas if c not in columnas]
    if faltantes:
        raise ValueError(
            f"Faltan columnas en Google Sheets: {faltantes}"
        )

    registros = []

    for numero_fila, fila in enumerate(valores[1:], start=2):
        if not any(str(x).strip() for x in fila):
            continue

        registro = {}
        for nombre, columna in columnas.items():
            indice = columna - 1
            registro[nombre] = (
                fila[indice] if indice < len(fila) else ""
            )

        registro["_fila"] = numero_fila
        registros.append(registro)

    return registros, columnas


def guardar_resultado(fila, sets_a, sets_b, columnas):
    datos = [
        {
            "range": f"{columna_letra(columnas['sets_a'])}{fila}",
            "values": [[sets_a]]
        },
        {
            "range": f"{columna_letra(columnas['sets_b'])}{fila}",
            "values": [[sets_b]]
        },
        {
            "range": f"{columna_letra(columnas['jugado'])}{fila}",
            "values": [["Si"]]
        }
    ]
    ws_partidos.batch_update(datos)


# =====================================================
# 5. AUTENTICACIÓN
# =====================================================

def autenticar(usuario_introducido, password_introducida, usuarios):
    admin_usuario = str(st.secrets.get("admin_username", "admin")).strip()
    admin_password = str(st.secrets["app_password"])

    if (
        normalizar(usuario_introducido) == normalizar(admin_usuario)
        and hmac.compare_digest(
            password_introducida.encode("utf-8"),
            admin_password.encode("utf-8")
        )
    ):
        return {
            "usuario": admin_usuario,
            "rol": "admin",
            "jugador": ""
        }

    for cuenta in usuarios:
        if normalizar(cuenta["usuario"]) != normalizar(usuario_introducido):
            continue

        if normalizar(cuenta["activo"]) not in ["si", "sí", "true", "1", "activo"]:
            return None

        if verificar_password(
            password_introducida,
            cuenta["password_hash"]
        ):
            return {
                "usuario": cuenta["usuario"],
                "rol": "jugador",
                "jugador": cuenta["jugador"]
            }

    return None


def mostrar_login(usuarios):
    st.subheader("Acceso a la liga")

    with st.form("login_form"):
        usuario = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button(
            "Entrar",
            use_container_width=True
        )

    if entrar:
        identidad = autenticar(usuario, password, usuarios)

        if identidad:
            st.session_state["authenticated"] = True
            st.session_state["identidad"] = identidad
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos, o cuenta inactiva.")


try:
    usuarios = leer_usuarios()
except Exception as e:
    st.error(f"No se han podido leer las cuentas de usuario: {e}")
    st.stop()

if not st.session_state.get("authenticated", False):
    mostrar_login(usuarios)
    st.stop()

identidad = st.session_state.get("identidad", {})
es_admin = identidad.get("rol") == "admin"
jugador_actual = identidad.get("jugador", "")

# Comprueba que la cuenta de jugador sigue activa y asociada a un jugador.
if not es_admin:
    cuenta_actual = next(
        (
            u for u in usuarios
            if normalizar(u["usuario"]) == normalizar(identidad.get("usuario", ""))
        ),
        None
    )

    if (
        cuenta_actual is None
        or normalizar(cuenta_actual["activo"]) not in ["si", "sí", "true", "1", "activo"]
        or not jugador_actual
    ):
        st.session_state.clear()
        st.error("Tu cuenta está inactiva o no está correctamente configurada.")
        st.stop()


# =====================================================
# 6. CARGAR INFORMACIÓN DE LA LIGA
# =====================================================

try:
    partidos, columnas = leer_datos()
    lista_jugadores = leer_jugadores()
except Exception as e:
    st.error(f"Error leyendo los datos: {e}")
    st.stop()


# =====================================================
# 7. FUNCIONES DE PERMISOS Y PRESENTACIÓN
# =====================================================

def participa_en_partido(nombre_jugador, partido):
    participantes = (
        separar_jugadores(partido["jugadores_a"])
        + separar_jugadores(partido["jugadores_b"])
    )
    return any(
        normalizar_nombre(nombre_jugador) == normalizar_nombre(nombre)
        for nombre in participantes
    )


def validar_resultado(sets_a, sets_b):
    return (
        (sets_a == "2" and sets_b in ["0", "1"])
        or
        (sets_b == "2" and sets_a in ["0", "1"])
    )


def mostrar_partido(partido, modo, prefijo):
    fila = partido["_fila"]
    jugadores_a = partido["jugadores_a"]
    jugadores_b = partido["jugadores_b"]
    fecha = partido.get("fecha", "")
    ya_jugado = es_jugado(partido["jugado"])

    es_participante = (
        es_admin or participa_en_partido(jugador_actual, partido)
    )

    puede_introducir = (
        es_admin or (es_participante and not ya_jugado)
    )

    with st.container(border=True):
        st.markdown(f"**Jornada {partido['jornada']} · Partido {partido['partido']}**")

        if fecha:
            st.caption(f"📅 {fecha}")

        col_a, col_vs, col_b = st.columns([4, 1, 4])

        with col_a:
            st.markdown(f"**{jugadores_a}**")
        with col_vs:
            st.markdown("### VS")
        with col_b:
            st.markdown(f"**{jugadores_b}**")

        if ya_jugado:
            st.success(
                f"Resultado: {partido['sets_a']} - {partido['sets_b']}"
            )
        else:
            st.warning("Pendiente de resultado")

        # Los jugadores solo pueden introducir resultados desde su calendario.
        # El administrador puede introducir o corregir cualquier resultado.
        if puede_introducir and (modo == "admin" or modo == "mi_calendario"):
            if es_admin or not ya_jugado:
                with st.form(f"resultado_{prefijo}_{fila}"):
                    st.markdown(
                        "**Introducir resultado**"
                        if not ya_jugado
                        else "**Corregir resultado (administrador)**"
                    )

                    opciones = ["", "0", "1", "2"]
                    actual_a = str(partido["sets_a"]).strip()
                    actual_b = str(partido["sets_b"]).strip()

                    c1, c2 = st.columns(2)

                    with c1:
                        sets_a = st.selectbox(
                            "Sets pareja A",
                            opciones,
                            index=opciones.index(actual_a) if actual_a in opciones else 0,
                            key=f"sa_{prefijo}_{fila}"
                        )

                    with c2:
                        sets_b = st.selectbox(
                            "Sets pareja B",
                            opciones,
                            index=opciones.index(actual_b) if actual_b in opciones else 0,
                            key=f"sb_{prefijo}_{fila}"
                        )

                    guardar = st.form_submit_button(
                        "Guardar resultado",
                        use_container_width=True
                    )

                if guardar:
                    # Validación de permisos en servidor, no solo en la interfaz.
                    if not es_admin:
                        if ya_jugado:
                            st.error("Este partido ya tiene resultado. Contacta con el administrador si hay un error.")
                            st.stop()

                        if not participa_en_partido(jugador_actual, partido):
                            st.error("No tienes permiso para modificar este partido.")
                            st.stop()

                    if not sets_a or not sets_b:
                        st.error("Debes introducir ambos resultados.")
                    elif not validar_resultado(sets_a, sets_b):
                        st.error(
                            "Resultado no válido. Solo se permiten "
                            "2-0, 2-1, 0-2 o 1-2."
                        )
                    elif (
                        len(separar_jugadores(jugadores_a)) != 2
                        or len(separar_jugadores(jugadores_b)) != 2
                    ):
                        st.error("Cada pareja debe contener exactamente dos jugadores separados por /.")
                    else:
                        try:
                            guardar_resultado(
                                fila,
                                int(sets_a),
                                int(sets_b),
                                columnas
                            )
                            st.success("Resultado guardado correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"No se pudo guardar el resultado: {e}")


def ordenar_jornadas(partidos):
    valores = sorted(
        {str(p["jornada"]) for p in partidos if p["jornada"]},
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x.lower())
    )
    return valores


# =====================================================
# 8. CALCULAR CLASIFICACIÓN INDIVIDUAL
# =====================================================

def calcular_clasificacion(partidos, lista_jugadores):
    estadisticas = {}

    for jugador in lista_jugadores:
        estadisticas[jugador] = {
            "PJ": 0,
            "PG": 0,
            "PP": 0,
            "SF": 0,
            "SC": 0,
            "Puntos": 0
        }

    avisos = []

    for p in partidos:
        if not es_jugado(p["jugado"]):
            continue

        try:
            sa = int(p["sets_a"])
            sb = int(p["sets_b"])
        except (ValueError, TypeError):
            avisos.append(f"Partido {p['partido']}: resultado incompleto.")
            continue

        if not (
            (sa == 2 and sb in [0, 1])
            or (sb == 2 and sa in [0, 1])
        ):
            avisos.append(f"Partido {p['partido']}: resultado inválido.")
            continue

        pareja_a = separar_jugadores(p["jugadores_a"])
        pareja_b = separar_jugadores(p["jugadores_b"])

        if len(pareja_a) != 2 or len(pareja_b) != 2:
            avisos.append(f"Partido {p['partido']}: parejas mal configuradas.")
            continue

        if len(set(pareja_a + pareja_b)) != 4:
            avisos.append(f"Partido {p['partido']}: hay jugadores duplicados.")
            continue

        for jugador in pareja_a + pareja_b:
            if jugador not in estadisticas:
                estadisticas[jugador] = {
                    "PJ": 0, "PG": 0, "PP": 0,
                    "SF": 0, "SC": 0, "Puntos": 0
                }

        victoria_a = sa > sb

        for jugador in pareja_a:
            estadisticas[jugador]["PJ"] += 1
            estadisticas[jugador]["SF"] += sa
            estadisticas[jugador]["SC"] += sb
            if victoria_a:
                estadisticas[jugador]["PG"] += 1
                estadisticas[jugador]["Puntos"] += 3
            else:
                estadisticas[jugador]["PP"] += 1

        for jugador in pareja_b:
            estadisticas[jugador]["PJ"] += 1
            estadisticas[jugador]["SF"] += sb
            estadisticas[jugador]["SC"] += sa
            if not victoria_a:
                estadisticas[jugador]["PG"] += 1
                estadisticas[jugador]["Puntos"] += 3
            else:
                estadisticas[jugador]["PP"] += 1

    columnas_vacias = [
        "Pos.", "Jugador", "PJ", "PG", "PP", "Ratio",
        "SF", "SC", "Diferencia", "Puntos"
    ]

    if not estadisticas:
        return pd.DataFrame(columns=columnas_vacias), avisos

    df = pd.DataFrame.from_dict(estadisticas, orient="index")
    df.index.name = "Jugador"
    df = df.reset_index()

    df["Diferencia"] = df["SF"] - df["SC"]
    df["Ratio_num"] = 0.0

    con_partidos = df["PJ"] > 0
    df.loc[con_partidos, "Ratio_num"] = (
        df.loc[con_partidos, "PG"] / df.loc[con_partidos, "PJ"]
    ) * 100

    df = df.sort_values(
        by=["Ratio_num", "Diferencia", "SF", "Jugador"],
        ascending=[False, False, False, True]
    ).reset_index(drop=True)

    df.insert(0, "Pos.", range(1, len(df) + 1))
    df["Ratio"] = df["Ratio_num"].map(lambda x: f"{x:.1f}%")
    df = df.drop(columns=["Ratio_num"])

    return df, avisos


# =====================================================
# 9. ADMINISTRACIÓN DE CUENTAS
# =====================================================

def crear_cuentas_faltantes(jugadores, usuarios_existentes):
    usuarios_por_jugador = {
        normalizar_nombre(u["jugador"])
        for u in usuarios_existentes
        if u["jugador"]
    }
    nombres_usuario = [u["usuario"] for u in usuarios_existentes]
    nuevas_cuentas = []

    for jugador in jugadores:
        if normalizar_nombre(jugador) in usuarios_por_jugador:
            continue

        usuario = generar_usuario(jugador, nombres_usuario)
        password = generar_password()

        ws_usuarios.append_row([
            usuario,
            hash_password(password),
            jugador,
            "jugador",
            "Si"
        ])

        nuevas_cuentas.append({
            "Jugador": jugador,
            "Usuario": usuario,
            "Contraseña inicial": password
        })
        nombres_usuario.append(usuario)
        usuarios_por_jugador.add(normalizar_nombre(jugador))

    return nuevas_cuentas


def restablecer_password(usuario_objetivo):
    valores = ws_usuarios.get_all_values()
    if not valores:
        raise ValueError("La pestaña Usuarios está vacía.")

    encabezados = [str(x).strip() for x in valores[0]]
    columnas_usuarios = {
        normalizar(nombre): i + 1
        for i, nombre in enumerate(encabezados)
    }

    col_usuario = columnas_usuarios["usuario"]
    col_hash = columnas_usuarios["password_hash"]

    for numero_fila, fila in enumerate(valores[1:], start=2):
        valor_usuario = fila[col_usuario - 1] if len(fila) >= col_usuario else ""
        if normalizar(valor_usuario) == normalizar(usuario_objetivo):
            nueva_password = generar_password()
            ws_usuarios.update_cell(
                numero_fila,
                col_hash,
                hash_password(nueva_password)
            )
            return nueva_password

    raise ValueError("No se ha encontrado el usuario.")


# =====================================================
# 10. INTERFAZ DE LA APLICACIÓN
# =====================================================

st.caption(
    f"Sesión: {'Administrador' if es_admin else jugador_actual}"
)

if es_admin:
    tab_general, tab_clasificacion, tab_usuarios = st.tabs([
        "📅 Calendario general",
        "🏆 Clasificación",
        "👥 Usuarios"
    ])
else:
    tab_general, tab_mio, tab_clasificacion = st.tabs([
        "📅 Calendario general",
        "🙋 Mi calendario",
        "🏆 Clasificación"
    ])


# -----------------------------------------------------
# 10A. CALENDARIO GENERAL
# -----------------------------------------------------

with tab_general:
    st.subheader("Calendario general")

    jornadas = ordenar_jornadas(partidos)

    if not jornadas:
        st.info("Todavía no hay jornadas disponibles.")
    else:
        jornada = st.selectbox(
            "Selecciona una jornada",
            jornadas,
            key="jornada_general"
        )

        partidos_jornada = [
            p for p in partidos
            if str(p["jornada"]) == str(jornada)
        ]

        jugados = sum(es_jugado(p["jugado"]) for p in partidos_jornada)

        st.caption(
            f"Jornada {jornada} · {jugados}/{len(partidos_jornada)} partidos jugados"
        )
        st.progress(jugados / len(partidos_jornada) if partidos_jornada else 0)

        for p in partidos_jornada:
            mostrar_partido(
                p,
                modo="admin" if es_admin else "general",
                prefijo="general"
            )


# -----------------------------------------------------
# 10B. CALENDARIO INDIVIDUAL
# -----------------------------------------------------

if not es_admin:
    with tab_mio:
        st.subheader(f"Mi calendario · {jugador_actual}")

        mis_partidos = [
            p for p in partidos
            if participa_en_partido(jugador_actual, p)
        ]

        if not mis_partidos:
            st.info("Todavía no tienes partidos asignados.")
        else:
            jornadas_mias = ordenar_jornadas(mis_partidos)
            jornada_mia = st.selectbox(
                "Filtrar por jornada",
                ["Todas"] + jornadas_mias,
                key="jornada_personal"
            )

            if jornada_mia == "Todas":
                partidos_mostrar = mis_partidos
            else:
                partidos_mostrar = [
                    p for p in mis_partidos
                    if str(p["jornada"]) == str(jornada_mia)
                ]

            total_mios = len(mis_partidos)
            jugados_mios = sum(es_jugado(p["jugado"]) for p in mis_partidos)

            m1, m2 = st.columns(2)
            m1.metric("Mis partidos", total_mios)
            m2.metric("Jugados", f"{jugados_mios}/{total_mios}")

            for p in partidos_mostrar:
                mostrar_partido(
                    p,
                    modo="mi_calendario",
                    prefijo="personal"
                )


# -----------------------------------------------------
# 10C. CLASIFICACIÓN
# -----------------------------------------------------

with tab_clasificacion:
    st.subheader("🏆 Clasificación individual")

    df, avisos = calcular_clasificacion(partidos, lista_jugadores)

    total_jugados = sum(es_jugado(p["jugado"]) for p in partidos)

    m1, m2, m3 = st.columns(3)
    m1.metric("Partidos jugados", total_jugados)
    m2.metric("Jugadores", len(df))
    m3.metric("Pendientes", len(partidos) - total_jugados)

    st.caption(
        "Orden: ratio de victorias → diferencia de sets → sets a favor."
    )

    st.dataframe(
        df[
            [
                "Pos.", "Jugador", "PJ", "PG", "PP",
                "Ratio", "SF", "SC", "Diferencia", "Puntos"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

    if avisos:
        with st.expander("⚠️ Revisar partidos con errores"):
            for aviso in avisos:
                st.warning(aviso)

    st.caption(
        "Los datos se calculan directamente desde los partidos "
        "marcados como Jugado = Si."
    )

    if not es_admin:
        estadistica_propia = df[
            df["Jugador"].apply(
                lambda x: normalizar_nombre(x) == normalizar_nombre(jugador_actual)
            )
        ]

        if not estadistica_propia.empty:
            st.divider()
            st.subheader("Mis estadísticas")
            st.dataframe(
                estadistica_propia,
                use_container_width=True,
                hide_index=True
            )


# -----------------------------------------------------
# 10D. PANEL DE ADMINISTRADOR
# -----------------------------------------------------

if es_admin:
    with tab_usuarios:
        st.subheader("Gestión de usuarios")

        st.write(
            "Desde aquí puedes generar las cuentas de los jugadores. "
            "La pestaña Usuarios de Google Sheets se crea automáticamente."
        )

        cuentas_por_jugador = {
            normalizar_nombre(u["jugador"])
            for u in usuarios
            if u["jugador"]
        }
        pendientes = [
            j for j in lista_jugadores
            if normalizar_nombre(j) not in cuentas_por_jugador
        ]

        st.metric("Cuentas creadas", len(usuarios))
        st.metric("Jugadores pendientes de cuenta", len(pendientes))

        if pendientes:
            st.warning(
                f"Hay {len(pendientes)} jugadores sin cuenta."
            )

            if st.button(
                "Generar cuentas para todos los jugadores pendientes",
                use_container_width=True
            ):
                try:
                    nuevas = crear_cuentas_faltantes(lista_jugadores, usuarios)
                    st.session_state["nuevas_credenciales"] = nuevas
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudieron crear las cuentas: {e}")
        else:
            st.success("Todos los jugadores tienen una cuenta.")

        nuevas = st.session_state.get("nuevas_credenciales", [])
        if nuevas:
            st.divider()
            st.subheader("Credenciales generadas")
            st.warning(
                "Copia o descarga estas contraseñas ahora y entrégalas "
                "a cada jugador por privado. Por seguridad, no se guardan "
                "en texto visible en Google Sheets."
            )

            df_credenciales = pd.DataFrame(nuevas)
            st.dataframe(
                df_credenciales,
                use_container_width=True,
                hide_index=True
            )

            csv = df_credenciales.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Descargar credenciales CSV",
                data=csv,
                file_name="credenciales_liga_padel.csv",
                mime="text/csv",
                use_container_width=True
            )

            if st.button("Ocultar credenciales de esta pantalla"):
                st.session_state.pop("nuevas_credenciales", None)
                st.rerun()

        st.divider()
        st.subheader("Cuentas existentes")

        usuarios_actuales = leer_usuarios()
        if usuarios_actuales:
            df_usuarios = pd.DataFrame([
                {
                    "Usuario": u["usuario"],
                    "Jugador": u["jugador"],
                    "Activo": u["activo"]
                }
                for u in usuarios_actuales
            ])
            st.dataframe(
                df_usuarios,
                use_container_width=True,
                hide_index=True
            )

            st.subheader("Restablecer contraseña")
            opciones_usuarios = [
                u["usuario"] for u in usuarios_actuales
            ]
            usuario_reset = st.selectbox(
                "Selecciona el usuario",
                opciones_usuarios,
                key="usuario_reset"
            )

            if st.button("Generar nueva contraseña", use_container_width=True):
                try:
                    password_nueva = restablecer_password(usuario_reset)
                    st.session_state["password_reset"] = {
                        "usuario": usuario_reset,
                        "password": password_nueva
                    }
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo restablecer la contraseña: {e}")

            reset = st.session_state.get("password_reset")
            if reset:
                st.success(
                    f"Nueva contraseña para {reset['usuario']}: "
                    f"**{reset['password']}**"
                )
                st.warning("Cópiala ahora y entrégala al jugador por privado.")
                if st.button("Ocultar contraseña"):
                    st.session_state.pop("password_reset", None)
                    st.rerun()
        else:
            st.info("Todavía no se han generado cuentas.")


# =====================================================
# 11. PIE DE PÁGINA Y CIERRE DE SESIÓN
# =====================================================

st.divider()

if st.button("Cerrar sesión"):
    st.session_state.clear()
    st.rerun()

st.caption("Liga de Pádel Roceña · Datos sincronizados con Google Sheets")
