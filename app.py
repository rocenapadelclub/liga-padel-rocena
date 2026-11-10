
import streamlit as st
import gspread
import pandas as pd
import hmac
import re
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
        max-width: 850px;
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

# =====================================================
# 2. AUTENTICACIÓN
# =====================================================

def login():
    st.subheader("Acceso a la liga")

    with st.form("login_form"):
        password = st.text_input(
            "Introduce la contraseña",
            type="password"
        )
        submitted = st.form_submit_button(
            "Entrar",
            use_container_width=True
        )

    if submitted:
        correct = st.secrets["app_password"]

        if hmac.compare_digest(password, correct):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")


if not st.session_state.get("authenticated", False):
    login()
    st.stop()

# =====================================================
# 3. CONEXIÓN GOOGLE SHEETS
# =====================================================

@st.cache_resource
def conectar_google():
    credentials = dict(st.secrets["gcp_service_account"])

    gc = gspread.service_account_from_dict(credentials)

    spreadsheet = gc.open_by_key(
        st.secrets["spreadsheet_id"]
    )

    partidos = spreadsheet.worksheet("Partidos")
    jugadores = spreadsheet.worksheet("Jugadores")

    return partidos, jugadores


try:
    ws_partidos, ws_jugadores = conectar_google()

except Exception as e:
    st.error("No se ha podido conectar con Google Sheets.")
    st.error(str(e))
    st.stop()


# =====================================================
# 4. FUNCIONES AUXILIARES
# =====================================================

def normalizar(texto):
    return str(texto).strip().lower()


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

    faltantes = [
        c for c in requeridas
        if c not in columnas
    ]

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


def leer_jugadores():

    valores = ws_jugadores.get_all_records()

    nombres = [
        str(fila.get("Jugador", "")).strip()
        for fila in valores
        if str(fila.get("Jugador", "")).strip()
    ]

    return nombres


def guardar_resultado(fila, sets_a, sets_b, columnas):

    # Actualizamos las tres celdas en una sola operación.
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
# 5. CARGAR INFORMACIÓN
# =====================================================

try:
    partidos, columnas = leer_datos()
    lista_jugadores = leer_jugadores()

except Exception as e:
    st.error(f"Error leyendo los datos: {e}")
    st.stop()


# =====================================================
# 6. PESTAÑAS PRINCIPALES
# =====================================================

tab_calendario, tab_clasificacion = st.tabs([
    "📅 Calendario y resultados",
    "🏆 Clasificación"
])


# =====================================================
# 7. PESTAÑA CALENDARIO
# =====================================================

with tab_calendario:

    st.subheader("Calendario de partidos")

    jornadas = sorted(
        set(p["jornada"] for p in partidos if p["jornada"]),
        key=lambda x: int(x) if str(x).isdigit() else str(x)
    )

    if not jornadas:
        st.info("Todavía no hay jornadas disponibles.")

    else:

        jornada = st.selectbox(
            "Selecciona una jornada",
            jornadas
        )

        partidos_jornada = [
            p for p in partidos
            if str(p["jornada"]) == str(jornada)
        ]

        jugados = sum(
            es_jugado(p["jugado"])
            for p in partidos_jornada
        )

        st.caption(
            f"Jornada {jornada} · "
            f"{jugados}/{len(partidos_jornada)} partidos jugados"
        )

        st.progress(
            jugados / len(partidos_jornada)
            if partidos_jornada else 0
        )

        for p in partidos_jornada:

            fila = p["_fila"]

            jugadores_a = p["jugadores_a"]
            jugadores_b = p["jugadores_b"]

            fecha = p.get("fecha", "")

            ya_jugado = es_jugado(p["jugado"])

            with st.container(border=True):

                st.markdown(
                    f"**Partido {p['partido']}**"
                )

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
                        f"Resultado: {p['sets_a']} - {p['sets_b']}"
                    )
                else:
                    st.warning("Pendiente de resultado")

                with st.form(f"resultado_{fila}"):

                    st.markdown(
                        "**Introducir / modificar resultado**"
                    )

                    c1, c2 = st.columns(2)

                    opciones = ["", "0", "1", "2"]

                    actual_a = str(p["sets_a"]).strip()
                    actual_b = str(p["sets_b"]).strip()

                    with c1:
                        sets_a = st.selectbox(
                            "Sets pareja A",
                            opciones,
                            index=(
                                opciones.index(actual_a)
                                if actual_a in opciones else 0
                            ),
                            key=f"sa_{fila}"
                        )

                    with c2:
                        sets_b = st.selectbox(
                            "Sets pareja B",
                            opciones,
                            index=(
                                opciones.index(actual_b)
                                if actual_b in opciones else 0
                            ),
                            key=f"sb_{fila}"
                        )

                    guardar = st.form_submit_button(
                        "Guardar resultado",
                        use_container_width=True
                    )

                    if guardar:

                        if not sets_a or not sets_b:
                            st.error("Debes introducir ambos resultados.")

                        elif not (
                            (sets_a == "2" and sets_b in ["0", "1"])
                            or
                            (sets_b == "2" and sets_a in ["0", "1"])
                        ):
                            st.error(
                                "Resultado no válido. "
                                "Solo se permiten 2-0, 2-1, 0-2 o 1-2."
                            )

                        elif len(separar_jugadores(jugadores_a)) != 2 or \
                             len(separar_jugadores(jugadores_b)) != 2:
                            st.error(
                                "Cada pareja debe contener exactamente "
                                "dos jugadores separados por /."
                            )

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
                                st.error(
                                    f"No se pudo guardar el resultado: {e}"
                                )


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
            avisos.append(
                f"Partido {p['partido']}: resultado incompleto."
            )
            continue

        if not (
            (sa == 2 and sb in [0, 1])
            or
            (sb == 2 and sa in [0, 1])
        ):
            avisos.append(
                f"Partido {p['partido']}: resultado inválido."
            )
            continue

        pareja_a = separar_jugadores(p["jugadores_a"])
        pareja_b = separar_jugadores(p["jugadores_b"])

        if len(pareja_a) != 2 or len(pareja_b) != 2:
            avisos.append(
                f"Partido {p['partido']}: parejas mal configuradas."
            )
            continue

        if len(set(pareja_a + pareja_b)) != 4:
            avisos.append(
                f"Partido {p['partido']}: hay jugadores duplicados."
            )
            continue

        for jugador in pareja_a + pareja_b:
            if jugador not in estadisticas:
                estadisticas[jugador] = {
                    "PJ": 0,
                    "PG": 0,
                    "PP": 0,
                    "SF": 0,
                    "SC": 0,
                    "Puntos": 0
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

    df = pd.DataFrame.from_dict(
        estadisticas,
        orient="index"
    )

    df.index.name = "Jugador"
    df = df.reset_index()

    # Calculamos diferencia y ratio de victorias
    df["Diferencia"] = df["SF"] - df["SC"]

    df["Ratio"] = 0.0
    partidos_jugados = df["PJ"] > 0

    df.loc[partidos_jugados, "Ratio"] = (
        df.loc[partidos_jugados, "PG"]
        / df.loc[partidos_jugados, "PJ"]
    ) * 100

    # Orden: ratio, diferencia de sets, sets a favor
    df = df.sort_values(
        by=["Ratio", "Diferencia", "SF", "Jugador"],
        ascending=[False, False, False, True]
    ).reset_index(drop=True)

    df.insert(0, "Pos.", range(1, len(df) + 1))

    # Formato porcentual
    df["Ratio"] = df["Ratio"].map(lambda x: f"{x:.1f}%")

    return df, avisos



# =====================================================
# 9. PESTAÑA CLASIFICACIÓN
# =====================================================

with tab_clasificacion:

    st.subheader("🏆 Clasificación individual")

    df, avisos = calcular_clasificacion(
        partidos,
        lista_jugadores
    )

    total_jugados = sum(
        es_jugado(p["jugado"])
        for p in partidos
    )

    m1, m2, m3 = st.columns(3)

    m1.metric("Partidos jugados", total_jugados)
    m2.metric("Jugadores", len(df))
    m3.metric(
        "Pendientes",
        len(partidos) - total_jugados
    )

    st.caption(
        "Orden: ratio de victorias → diferencia de sets → sets a favor."
    )

    st.dataframe(
        df[
            [
                "Pos.",
                "Jugador",
                "PJ",
                "PG",
                "PP",
                "Ratio",
                "SF",
                "SC",
                "Diferencia",
                "Puntos"
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


# =====================================================
# 10. PIE DE PÁGINA
# =====================================================

st.divider()

if st.button("Cerrar sesión"):
    st.session_state["authenticated"] = False
    st.rerun()

st.caption("Liga de Pádel Roceña · Actualización desde Google Sheets")
