import streamlit as st
import pandas as pd
from datetime import datetime, date
from io import BytesIO
import os
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
import base64

# --- 1. CONSTANTES Y CONFIGURACIÓN INICIAL ---
DATA_FILE = "registro_data.pkl"
DEPOSITS_FILE = "registro_depositos.pkl"
DEBIT_NOTES_FILE = "registro_notas_debito.pkl"

INITIAL_ACCUMULATED_BALANCE = 176.01 # Valor cambiado de 170.30 a 176.01
PRODUCT_NAME = "Pollo"
LBS_PER_KG = 2.20462

PROVEEDORES = ["LIRIS SA", "Gallina 1", "Monze Anzules", "Medina"]
TIPOS_DOCUMENTO = ["Factura", "Nota de debito", "Nota de credito"]
AGENCIAS = [
    "Cajero Automatico Pichincha", "Cajero Automatico Pacifico",
    "Cajero Automatico Guayaquil", "Cajero Automatico Bolivariano",
    "Banco Pichincha", "Banco del Pacifico", "Banco de Guayaquil",
    "Banco Bolivariano"
]

# Columnas esperadas para los DataFrames (asegurar consistencia)
COLUMNS_DATA = [
    "N", "Fecha", "Proveedor", "Producto", "Cantidad",
    "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
    "Cantidad de gavetas", "Precio Unitario ($)", "Promedio",
    "Kilos Restantes", "Libras Restantes", "Total ($)",
    "Monto Deposito", "Saldo diario", "Saldo Acumulado"
]
COLUMNS_DEPOSITS = ["Fecha", "Empresa", "Agencia", "Monto", "Documento", "N"]
COLUMNS_DEBIT_NOTES = ["Fecha", "Libras calculadas", "Descuento", "Descuento posible", "Descuento real"]

# Configuración de la página de Streamlit
st.set_page_config(page_title="Sistema de Gestión de Proveedores - Producto Pollo", layout="wide", initial_sidebar_state="expanded")

# --- 2. FUNCIONES DE CARGA Y GUARDADO DE DATOS ---
@st.cache_data(show_spinner=False) # Caching para mejorar el rendimiento al cargar datos
def load_dataframe(file_path, default_columns, date_columns=None):
    """Carga un DataFrame desde un archivo pickle o crea uno vacío."""
    if os.path.exists(file_path):
        try:
            df = pd.read_pickle(file_path)
            if date_columns:
                for col in date_columns:
                    if col in df.columns:
                        # Convertir a datetime y luego a date para uniformidad
                        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
            # Asegurar que todas las columnas por defecto existen, añadiéndolas si faltan
            for col in default_columns:
                if col not in df.columns:
                    df[col] = None # O un valor por defecto adecuado
            return df[default_columns] # Retornar con el orden de columnas esperado
        except Exception as e:
            st.error(f"Error al cargar {file_path}: {e}. Creando DataFrame vacío.")
            return pd.DataFrame(columns=default_columns)
    else:
        return pd.DataFrame(columns=default_columns)

def save_dataframe(df, file_path):
    """Guarda un DataFrame en un archivo pickle."""
    try:
        df.to_pickle(file_path)
        return True
    except Exception as e:
        st.error(f"Error al guardar {file_path}: {e}")
        return False

# --- 3. FUNCIONES DE INICIALIZACIÓN DEL ESTADO ---
def initialize_session_state():
    """Inicializa todos los DataFrames en st.session_state."""
    if "data" not in st.session_state:
        st.session_state.data = load_dataframe(DATA_FILE, COLUMNS_DATA, ["Fecha"])
        
        # Asegurar que la fila de balance inicial exista y sea la primera
        initial_balance_row_exists = any(st.session_state.data["Proveedor"] == "BALANCE_INICIAL")

        if not initial_balance_row_exists:
            fila_inicial_saldo = {col: None for col in COLUMNS_DATA}
            fila_inicial_saldo["Fecha"] = datetime(1900, 1, 1).date() # Fecha muy antigua para que siempre sea primera
            fila_inicial_saldo["Proveedor"] = "BALANCE_INICIAL"
            fila_inicial_saldo["Saldo diario"] = 0.00
            fila_inicial_saldo["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
            fila_inicial_saldo["Monto Deposito"] = 0.0
            fila_inicial_saldo["Total ($)"] = 0.0
            fila_inicial_saldo["N"] = "00" # Un N especial para el balance inicial

            # Si el DataFrame está vacío o no tiene la fila de balance inicial, añadirla.
            if st.session_state.data.empty:
                st.session_state.data = pd.DataFrame([fila_inicial_saldo])
            else:
                st.session_state.data = pd.concat([pd.DataFrame([fila_inicial_saldo]), st.session_state.data], ignore_index=True)
        else:
            # Si "BALANCE_INICIAL" existe, asegurar sus valores correctos
            initial_balance_idx = st.session_state.data[st.session_state.data["Proveedor"] == "BALANCE_INICIAL"].index
            if not initial_balance_idx.empty:
                idx = initial_balance_idx[0]
                st.session_state.data.loc[idx, "Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
                st.session_state.data.loc[idx, "Saldo diario"] = 0.0
                st.session_state.data.loc[idx, "Monto Deposito"] = 0.0
                st.session_state.data.loc[idx, "Total ($)"] = 0.0
                st.session_state.data.loc[idx, "N"] = "00"
                # Asegurar que la fecha sea datetime.date
                st.session_state.data.loc[idx, "Fecha"] = datetime(1900, 1, 1).date()


    if "df" not in st.session_state:
        st.session_state.df = load_dataframe(DEPOSITS_FILE, COLUMNS_DEPOSITS, ["Fecha"])
        # Asegurar que la columna 'N' sea string
        st.session_state.df["N"] = st.session_state.df["N"].astype(str)

    if "notas" not in st.session_state:
        st.session_state.notas = load_dataframe(DEBIT_NOTES_FILE, COLUMNS_DEBIT_NOTES, ["Fecha"])

    # Recalcular saldos acumulados de forma robusta al inicio o cuando los datos cambian
    recalculate_accumulated_balances()
    
    # Inicializar flags para controlar reruns
    if "deposit_added" not in st.session_state: st.session_state.deposit_added = False
    if "deposit_deleted" not in st.session_state: st.session_state.deposit_deleted = False
    if "record_added" not in st.session_state: st.session_state.record_added = False
    if "record_deleted" not in st.session_state: st.session_state.record_deleted = False
    if "data_imported" not in st.session_state: st.session_state.data_imported = False
    if "debit_note_added" not in st.session_state: st.session_state.debit_note_added = False
    if "debit_note_deleted" not in st.session_state: st.session_state.debit_note_deleted = False
    if "record_edited" not in st.session_state: st.session_state.record_edited = False
    if "deposit_edited" not in st.session_state: st.session_state.deposit_edited = False
    if "debit_note_edited" not in st.session_state: st.session_state.debit_note_edited = False


# --- 4. FUNCIONES DE LÓGICA DE NEGOCIO Y CÁLCULOS ---
def recalculate_accumulated_balances():
    """
    Recalcula el Saldo Acumulado para todo el DataFrame de registros
    basándose en los saldos diarios y las notas de débito.
    Esta función es crítica y debe ser robusta.
    """
    df_data = st.session_state.data.copy()
    df_deposits = st.session_state.df.copy()
    df_notes = st.session_state.notas.copy()

    # Asegurarse de que las columnas de fecha sean datetime.date para comparaciones y ordenamiento
    for df_temp in [df_data, df_deposits, df_notes]:
        if "Fecha" in df_temp.columns:
            df_temp["Fecha"] = pd.to_datetime(df_temp["Fecha"], errors="coerce").dt.date

    # Separar la fila de 'BALANCE_INICIAL' para que no afecte los cálculos operativos
    df_initial_balance = df_data[df_data["Proveedor"] == "BALANCE_INICIAL"].copy()
    df_data_operaciones = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()

    # --- Pre-procesamiento y cálculos para df_data_operaciones ---
    # Asegurarse que las columnas de números son numéricas
    numeric_cols_data = ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)", "Monto Deposito", "Total ($)", "Saldo diario", "Saldo Acumulado", "Kilos Restantes", "Libras Restantes", "Promedio", "Cantidad de gavetas"]
    for col in numeric_cols_data:
        if col in df_data_operaciones.columns:
            df_data_operaciones[col] = pd.to_numeric(df_data_operaciones[col], errors='coerce').fillna(0)

    # Calcular Kilos Restantes, Libras Restantes, Promedio, Total ($)
    if not df_data_operaciones.empty:
        df_data_operaciones["Kilos Restantes"] = df_data_operaciones["Peso Salida (kg)"] - df_data_operaciones["Peso Entrada (kg)"]
        df_data_operaciones["Libras Restantes"] = df_data_operaciones["Kilos Restantes"] * LBS_PER_KG
        df_data_operaciones["Promedio"] = df_data_operaciones.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
        df_data_operaciones["Total ($)"] = df_data_operaciones["Libras Restantes"] * df_data_operaciones["Precio Unitario ($)"]
    else:
        # Si no hay operaciones, asegurar que estas columnas existen con values por defecto
        for col in ["Kilos Restantes", "Libras Restantes", "Promedio", "Total ($)"]:
            if col not in df_data_operaciones.columns:
                df_data_operaciones[col] = 0.0

    # --- Calcular Monto Deposito para df_data_operaciones ---
    # Asegurarse que 'Monto' sea numérico en df_deposits
    if not df_deposits.empty:
        df_deposits["Monto"] = pd.to_numeric(df_deposits["Monto"], errors='coerce').fillna(0)
        
        # Agrupar depósitos por Fecha y Empresa
        deposits_summary = df_deposits.groupby(["Fecha", "Empresa"])["Monto"].sum().reset_index()
        deposits_summary.rename(columns={"Monto": "Monto Deposito Calculado"}, inplace=True)

        # Crear una columna temporal 'Empresa_key' en df_data_operaciones para la fusión
        df_data_operaciones["Empresa_key"] = df_data_operaciones["Proveedor"]

        # Fusionar los depósitos calculados con los datos de registro (solo para operaciones)
        df_data_operaciones = pd.merge(
            df_data_operaciones.drop(columns=["Monto Deposito"], errors='ignore'), # Eliminar columna existente para evitar duplicados
            deposits_summary,
            left_on=["Fecha", "Empresa_key"],
            right_on=["Fecha", "Empresa"],
            how="left"
        )
        df_data_operaciones["Monto Deposito"] = df_data_operaciones["Monto Deposito Calculado"].fillna(0)
        df_data_operaciones.drop(columns=["Monto Deposito Calculado", "Empresa", "Empresa_key"], inplace=True, errors='ignore')
    else:
        # Si no hay depósitos, el Monto Deposito para todas las operaciones es 0
        df_data_operaciones["Monto Deposito"] = 0.0

    # Calcular Saldo diario para operaciones (sin incluir el balance inicial)
    df_data_operaciones["Saldo diario"] = df_data_operaciones["Monto Deposito"] - df_data_operaciones["Total ($)"]

    # Incorporar notas de débito al saldo diario consolidado
    if not df_notes.empty:
        df_notes["Descuento real"] = pd.to_numeric(df_notes["Descuento real"], errors='coerce').fillna(0)
        notes_by_date = df_notes.groupby("Fecha")["Descuento real"].sum().reset_index()
        notes_by_date.rename(columns={"Descuento real": "NotaDebitoAjuste"}, inplace=True)
        
        # Agrupar el saldo diario de operaciones por fecha
        daily_ops_saldo = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()

        # Fusionar con las notas de débito
        full_daily_balances = pd.merge(daily_ops_saldo, notes_by_date, on="Fecha", how="left")
        full_daily_balances["NotaDebitoAjuste"] = full_daily_balances["NotaDebitoAjuste"].fillna(0)
        # Las notas de débito reducen el saldo, por eso se restan (o se suman un valor negativo)
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["Saldo diario"] + full_daily_balances["NotaDebitoAjuste"]
    else:
        full_daily_balances = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["Saldo diario"]
    
    # Ordenar por fecha para la suma acumulada
    full_daily_balances = full_daily_balances.sort_values("Fecha")

    # Calcular Saldo Acumulado, partiendo de INITIAL_ACCUMULATED_BALANCE
    full_daily_balances["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + full_daily_balances["SaldoDiarioAjustado"].cumsum()

    # Mapear los saldos diarios y acumulados de vuelta a df_data_operaciones
    saldo_diario_map = full_daily_balances.set_index("Fecha")["SaldoDiarioAjustado"].to_dict()
    saldo_acumulado_map = full_daily_balances.set_index("Fecha")["Saldo Acumulado"].to_dict()
    
    if not df_data_operaciones.empty:
        df_data_operaciones["Saldo diario"] = df_data_operaciones["Fecha"].map(saldo_diario_map).fillna(0)
        # Aquí asignamos el saldo acumulado del *final del día* a todas las entradas de ese día
        df_data_operaciones["Saldo Acumulado"] = df_data_operaciones["Fecha"].map(saldo_acumulado_map).fillna(INITIAL_ACCUMULATED_BALANCE)
    
    # Consolidar el DataFrame final, incluyendo la fila de BALANCE_INICIAL
    if not df_initial_balance.empty:
        df_initial_balance.loc[:, "Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
        df_initial_balance.loc[:, "Saldo diario"] = 0.0
        df_initial_balance.loc[:, "Monto Deposito"] = 0.0
        df_initial_balance.loc[:, "Total ($)"] = 0.0
        df_initial_balance.loc[:, "N"] = "00"
        df_initial_balance.loc[:, "Fecha"] = datetime(1900, 1, 1).date()
        
        df_data = pd.concat([df_initial_balance, df_data_operaciones], ignore_index=True)
    else:
        df_data = df_data_operaciones

    # Asegurar todas las columnas en el orden correcto
    df_data = df_data[COLUMNS_DATA]
    
    # Ordenar el DataFrame final por Fecha y luego por N
    # Asegurarse que 'N' sea string para un correcto ordenamiento alfanumérico si es necesario
    df_data["N"] = df_data["N"].astype(str)
    df_data = df_data.sort_values(by=["Fecha", "N"], ascending=[True, True]).reset_index(drop=True)

    # El Saldo Acumulado se mapea una vez por fecha, por lo que es constante para una fecha dada.
    # No se necesita una iteración adicional para el saldo acumulado aquí si ya se mapeó el saldo final del día.
    
    # Finalmente, actualizar st.session_state.data
    st.session_state.data = df_data
    save_dataframe(st.session_state.data, DATA_FILE)


def get_next_n(df, current_date):
    """Genera el siguiente número 'N' para un registro basado en el N más alto globalmente."""
    # Convertir 'N' a numérico para poder encontrar el máximo, ignorando '00' del balance inicial
    df_filtered = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    
    if not df_filtered.empty:
        df_filtered["N_numeric"] = pd.to_numeric(df_filtered["N"], errors='coerce').fillna(0)
        max_n_global = df_filtered["N_numeric"].max()
        return f"{int(max_n_global) + 1:02}"
    else:
        return "01" # Si no hay registros, empezar con "01"


def add_deposit_record(fecha_d, empresa, agencia, monto):
    """Agrega un nuevo registro de depósito."""
    df_actual = st.session_state.df.copy()
    
    # Asegurarse que la columna 'N' sea string
    df_actual["N"] = df_actual["N"].astype(str)

    # Generar un 'N' único y secuencial globalmente para depósitos
    if not df_actual.empty:
        # Filtrar valores no numéricos antes de encontrar el máximo
        valid_n_deposits = df_actual[df_actual["N"].str.isdigit()]["N"].astype(int)
        max_n_deposit = valid_n_deposits.max() if not valid_n_deposits.empty else 0
        numero = f"{max_n_deposit + 1:02}"
    else:
        numero = "01" # Primer depósito

    documento = "Deposito" if "Cajero" in agencia else "Transferencia"
    
    nuevo_registro = {
        "Fecha": fecha_d,
        "Empresa": empresa,
        "Agencia": agencia,
        "Monto": float(monto), # Asegurar tipo numérico
        "Documento": documento,
        "N": numero
    }
    st.session_state.df = pd.concat([df_actual, pd.DataFrame([nuevo_registro])], ignore_index=True)
    if save_dataframe(st.session_state.df, DEPOSITS_FILE):
        st.session_state.deposit_added = True
        st.success("Deposito agregado exitosamente. Recalculando saldos...")
    else:
        st.error("Error al guardar el depósito.")

def delete_deposit_record(index_to_delete):
    """Elimina un registro de depósito por su índice real en el DataFrame."""
    try:
        st.session_state.df = st.session_state.df.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.df, DEPOSITS_FILE):
            st.session_state.deposit_deleted = True
            st.success("Deposito eliminado correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar el depósito.")
    except IndexError:
        st.error("Índice de depósito no válido para eliminar.")
    except KeyError:
        st.error("El índice de depósito seleccionado ya no existe.")


def edit_deposit_record(index_to_edit, updated_data):
    """Edita un registro de depósito por su índice real en el DataFrame."""
    try:
        current_df = st.session_state.df.copy()
        
        if index_to_edit not in current_df.index:
            st.error("El índice de depósito a editar no es válido o ya no existe.")
            return

        for key, value in updated_data.items():
            if key == "Monto":
                current_df.loc[index_to_edit, key] = float(value)
            elif key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            else:
                current_df.loc[index_to_edit, key] = value
        
        # Actualizar el tipo de documento si la agencia ha cambiado
        agencia = updated_data.get("Agencia", current_df.loc[index_to_edit, "Agencia"])
        current_df.loc[index_to_edit, "Documento"] = "Deposito" if "Cajero" in str(agencia) else "Transferencia"

        st.session_state.df = current_df
        if save_dataframe(st.session_state.df, DEPOSITS_FILE):
            st.session_state.deposit_edited = True
            st.success("Deposito editado exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios del depósito.")
    except Exception as e:
        st.error(f"Error al editar el depósito: {e}")
        st.exception(e)


def add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, tipo_documento, gavetas, precio_unitario):
    """Agrega un nuevo registro de proveedor."""
    df = st.session_state.data.copy()

    # Validación de entradas
    if not all(isinstance(val, (int, float)) and val >= 0 for val in [cantidad, peso_salida, peso_entrada, precio_unitario, gavetas]):
        st.error("Los valores numéricos no pueden ser negativos y deben ser números.")
        return False
    if cantidad == 0 and peso_salida == 0 and peso_entrada == 0:
        st.error("Por favor, ingresa una Cantidad y/o Pesos válidos (no pueden ser todos cero).")
        return False
    if peso_entrada > peso_salida:
        st.error("El Peso Entrada (kg) no puede ser mayor que el Peso Salida (kg).")
        return False

    kilos_restantes = peso_salida - peso_entrada
    libras_restantes = kilos_restantes * LBS_PER_KG
    promedio = libras_restantes / cantidad if cantidad != 0 else 0
    total = libras_restantes * precio_unitario

    # Generar el número 'N'
    enumeracion = get_next_n(df, fecha)

    nueva_fila = {
        "N": enumeracion,
        "Fecha": fecha,
        "Proveedor": proveedor,
        "Producto": PRODUCT_NAME,
        "Cantidad": int(cantidad),
        "Peso Salida (kg)": float(peso_salida),
        "Peso Entrada (kg)": float(peso_entrada),
        "Tipo Documento": tipo_documento,
        "Cantidad de gavetas": int(gavetas),
        "Precio Unitario ($)": float(precio_unitario),
        "Promedio": promedio,
        "Kilos Restantes": kilos_restantes,
        "Libras Restantes": libras_restantes,
        "Total ($)": total,
        "Monto Deposito": 0.0, # Se llenará con el recalculado
        "Saldo diario": 0.0,  # Se llenará con el recalculado
        "Saldo Acumulado": 0.0 # Se llenará con el recalculado
    }

    # Separar la fila de balance inicial para luego concatenar
    df_balance = df[df["Proveedor"] == "BALANCE_INICIAL"].copy()
    df_temp = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    df_temp = pd.concat([df_temp, pd.DataFrame([nueva_fila])], ignore_index=True)
    
    df_temp.reset_index(drop=True, inplace=True)

    st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)
    
    if save_dataframe(st.session_state.data, DATA_FILE):
        st.session_state.record_added = True
        st.success("Registro agregado correctamente. Recalculando saldos...")
        return True
    else:
        st.error("Error al guardar el registro.")
        return False

def delete_record(index_to_delete):
    """Elimina un registro de la tabla principal por su índice real."""
    try:
        # Asegurarse de no eliminar la fila de BALANCE_INICIAL
        if st.session_state.data.loc[index_to_delete, "Proveedor"] == "BALANCE_INICIAL":
            st.error("No se puede eliminar la fila de BALANCE_INICIAL.")
            return

        st.session_state.data = st.session_state.data.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.data, DATA_FILE):
            st.session_state.record_deleted = True
            st.success("Registro eliminado correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar el registro.")
    except IndexError:
        st.error("Índice de registro no válido para eliminar.")
    except KeyError:
        st.error("El índice de registro seleccionado ya no existe.")


def edit_supplier_record(index_to_edit, updated_data):
    """Edita un registro de proveedor por su índice real en el DataFrame."""
    try:
        current_df = st.session_state.data.copy()
        
        # Asegurarse de no editar la fila de BALANCE_INICIAL (excepto su saldo si es necesario, pero eso se maneja en recalculate)
        if current_df.loc[index_to_edit, "Proveedor"] == "BALANCE_INICIAL":
            st.error("No se puede editar la fila de BALANCE_INICIAL directamente aquí.")
            return

        # Actualizar los datos del registro
        for key, value in updated_data.items():
            if key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            elif key in ["Cantidad", "Cantidad de gavetas"]:
                current_df.loc[index_to_edit, key] = int(value)
            elif key in ["Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
                current_df.loc[index_to_edit, key] = float(value)
            else:
                current_df.loc[index_to_edit, key] = value
        
        # Recalcular columnas dependientes (Kilos Restantes, Libras Restantes, Promedio, Total)
        peso_salida = current_df.loc[index_to_edit, "Peso Salida (kg)"]
        peso_entrada = current_df.loc[index_to_edit, "Peso Entrada (kg)"]
        cantidad = current_df.loc[index_to_edit, "Cantidad"]
        precio_unitario = current_df.loc[index_to_edit, "Precio Unitario ($)"]

        kilos_restantes = peso_salida - peso_entrada
        libras_restantes = kilos_restantes * LBS_PER_KG
        promedio = libras_restantes / cantidad if cantidad != 0 else 0
        total = libras_restantes * precio_unitario

        current_df.loc[index_to_edit, "Kilos Restantes"] = kilos_restantes
        current_df.loc[index_to_edit, "Libras Restantes"] = libras_restantes
        current_df.loc[index_to_edit, "Promedio"] = promedio
        current_df.loc[index_to_edit, "Total ($)"] = total

        st.session_state.data = current_df
        if save_dataframe(st.session_state.data, DATA_FILE):
            st.session_state.record_edited = True
            st.success("Registro editado exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios del registro.")
    except Exception as e:
        st.error(f"Error al editar el registro: {e}")
        st.exception(e)

def import_excel_data(archivo_excel):
    """Importa datos desde un archivo Excel y los añade a los registros."""
    try:
        # Usar pd.ExcelFile para leer múltiples hojas
        xls = pd.ExcelFile(archivo_excel)
        sheet_names = xls.sheet_names
        
        # --- Hoja 1: Registro de Proveedores ---
        df_proveedores_importado = pd.DataFrame(columns=COLUMNS_DATA)
        if "registro de proveedores" in sheet_names: # Reemplaza con el nombre exacto de tu hoja
            df_proveedores_importado = pd.read_excel(xls, sheet_name="registro de proveedores")
            st.write("Vista previa de los datos de **Registro de Proveedores** importados:", df_proveedores_importado.head())

            columnas_requeridas_proveedores = [
                "Fecha", "Proveedor", "Cantidad",
                "Peso Salida (kg)", "Peso Entrada (kg)", "Tipo Documento",
                "Cantidad de gavetas", "Precio Unitario ($)"
            ]
            if not all(col in df_proveedores_importado.columns for col in columnas_requeridas_proveedores):
                st.warning(f"La hoja 'registro de proveedores' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_proveedores)}. Se omitirá esta hoja.")
                df_proveedores_importado = pd.DataFrame(columns=COLUMNS_DATA) # Resetear para no añadir datos inválidos
            else:
                # Preparar datos importados de proveedores
                df_proveedores_importado["Fecha"] = pd.to_datetime(df_proveedores_importado["Fecha"], errors="coerce").dt.date
                df_proveedores_importado.dropna(subset=["Fecha"], inplace=True)

                for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)", "Cantidad de gavetas"]:
                    df_proveedores_importado[col] = pd.to_numeric(df_proveedores_importado[col], errors='coerce').fillna(0)
                
                df_proveedores_importado["Kilos Restantes"] = df_proveedores_importado["Peso Salida (kg)"] - df_proveedores_importado["Peso Entrada (kg)"]
                df_proveedores_importado["Libras Restantes"] = df_proveedores_importado["Kilos Restantes"] * LBS_PER_KG
                df_proveedores_importado["Promedio"] = df_proveedores_importado.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
                df_proveedores_importado["Total ($)"] = df_proveedores_importado["Libras Restantes"] * df_proveedores_importado["Precio Unitario ($)"]
                
                # Asignar 'N' secuencial
                current_ops_data = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
                max_n_existing_proveedores = 0
                if not current_ops_data.empty:
                    max_n_existing_proveedores = current_ops_data["N"].apply(lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0).max()
                
                new_n_counter_proveedores = max_n_existing_proveedores + 1
                df_proveedores_importado["N"] = [f"{new_n_counter_proveedores + i:02}" for i in range(len(df_proveedores_importado))]
                
                df_proveedores_importado["Monto Deposito"] = 0.0
                df_proveedores_importado["Saldo diario"] = 0.0
                df_proveedores_importado["Saldo Acumulado"] = 0.0
                df_proveedores_importado["Producto"] = PRODUCT_NAME
                df_proveedores_importado = df_proveedores_importado[COLUMNS_DATA] # Asegurar el orden

        else:
            st.warning("La hoja 'registro de proveedores' no se encontró en el archivo Excel. Se omitirá esta importación.")

        # --- Hoja 2: Registro de Depósitos ---
        df_depositos_importado = pd.DataFrame(columns=COLUMNS_DEPOSITS)
        if "registro de depositos" in sheet_names: # Reemplaza con el nombre exacto de tu hoja
            df_depositos_importado = pd.read_excel(xls, sheet_name="registro de depositos")
            st.write("Vista previa de los datos de **Registro de Depósitos** importados:", df_depositos_importado.head())

            columnas_requeridas_depositos = ["Fecha", "Empresa", "Agencia", "Monto"]
            if not all(col in df_depositos_importado.columns for col in columnas_requeridas_depositos):
                st.warning(f"La hoja 'registro de depositos' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_depositos)}. Se omitirá esta hoja.")
                df_depositos_importado = pd.DataFrame(columns=COLUMNS_DEPOSITS)
            else:
                df_depositos_importado["Fecha"] = pd.to_datetime(df_depositos_importado["Fecha"], errors="coerce").dt.date
                df_depositos_importado.dropna(subset=["Fecha"], inplace=True)
                df_depositos_importado["Monto"] = pd.to_numeric(df_depositos_importado["Monto"], errors='coerce').fillna(0)
                
                # Asignar 'N' y 'Documento' para depósitos importados
                current_deposits_data = st.session_state.df.copy()
                max_n_existing_deposits = 0
                if not current_deposits_data.empty:
                    valid_n_deposits = current_deposits_data[current_deposits_data["N"].str.isdigit()]["N"].astype(int)
                    max_n_existing_deposits = valid_n_deposits.max() if not valid_n_deposits.empty else 0
                
                new_n_counter_deposits = max_n_existing_deposits + 1
                df_depositos_importado["N"] = [f"{new_n_counter_deposits + i:02}" for i in range(len(df_depositos_importado))]
                df_depositos_importado["Documento"] = df_depositos_importado["Agencia"].apply(lambda x: "Deposito" if "Cajero" in str(x) else "Transferencia")
                df_depositos_importado = df_depositos_importado[COLUMNS_DEPOSITS] # Asegurar el orden
        else:
            st.warning("La hoja 'registro de depositos' no se encontró en el archivo Excel. Se omitirá esta importación.")

        # --- Hoja 3: Registro de Notas de Debito ---
        df_notas_debito_importado = pd.DataFrame(columns=COLUMNS_DEBIT_NOTES)
        if "registro de notas de debito" in sheet_names: # Reemplaza con el nombre exacto de tu hoja
            df_notas_debito_importado = pd.read_excel(xls, sheet_name="registro de notas de debito")
            st.write("Vista previa de los datos de **Registro de Notas de Debito** importados:", df_notas_debito_importado.head())

            columnas_requeridas_notas = ["Fecha", "Descuento", "Descuento real"]
            if not all(col in df_notas_debito_importado.columns for col in columnas_requeridas_notas):
                st.warning(f"La hoja 'registro de notas de debito' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_notas)}. Se omitirá esta hoja.")
                df_notas_debito_importado = pd.DataFrame(columns=COLUMNS_DEBIT_NOTES)
            else:
                df_notas_debito_importado["Fecha"] = pd.to_datetime(df_notas_debito_importado["Fecha"], errors="coerce").dt.date
                df_notas_debito_importado.dropna(subset=["Fecha"], inplace=True)
                df_notas_debito_importado["Descuento"] = pd.to_numeric(df_notas_debito_importado["Descuento"], errors='coerce').fillna(0)
                df_notas_debito_importado["Descuento real"] = pd.to_numeric(df_notas_debito_importado["Descuento real"], errors='coerce').fillna(0)

                # Recalcular "Libras calculadas" y "Descuento posible" para las notas importadas
                if not df_notas_debito_importado.empty and not st.session_state.data.empty:
                    df_data_for_calc_notes = st.session_state.data.copy()
                    df_data_for_calc_notes["Libras Restantes"] = pd.to_numeric(df_data_for_calc_notes["Libras Restantes"], errors='coerce').fillna(0)
                    
                    df_notas_debito_importado["Libras calculadas"] = df_notas_debito_importado["Fecha"].apply(
                        lambda f: df_data_for_calc_notes[
                            (df_data_for_calc_notes["Fecha"] == f) & 
                            (df_data_for_calc_notes["Proveedor"] != "BALANCE_INICIAL")
                        ]["Libras Restantes"].sum()
                    )
                    df_notas_debito_importado["Descuento posible"] = df_notas_debito_importado["Libras calculadas"] * df_notas_debito_importado["Descuento"]
                else:
                     df_notas_debito_importado["Libras calculadas"] = 0.0
                     df_notas_debito_importado["Descuento posible"] = 0.0
                
                df_notas_debito_importado = df_notas_debito_importado[COLUMNS_DEBIT_NOTES] # Asegurar el orden

        else:
            st.warning("La hoja 'registro de notas de debito' no se encontró en el archivo Excel. Se omitirá esta importación.")

        if st.button("Cargar datos a registros desde Excel"):
            # Concatenar el DataFrame importado de proveedores
            if not df_proveedores_importado.empty:
                df_balance = st.session_state.data[st.session_state.data["Proveedor"] == "BALANCE_INICIAL"].copy()
                df_temp = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
                st.session_state.data = pd.concat([df_balance, df_temp, df_proveedores_importado], ignore_index=True)
                st.session_state.data.reset_index(drop=True, inplace=True)
                save_dataframe(st.session_state.data, DATA_FILE)
                st.session_state.data_imported = True
            
            # Concatenar el DataFrame importado de depósitos
            if not df_depositos_importado.empty:
                st.session_state.df = pd.concat([st.session_state.df, df_depositos_importado], ignore_index=True)
                st.session_state.df["N"] = st.session_state.df["N"].astype(str) # Asegurar que 'N' sea string
                save_dataframe(st.session_state.df, DEPOSITS_FILE)
                st.session_state.data_imported = True

            # Concatenar el DataFrame importado de notas de débito
            if not df_notas_debito_importado.empty:
                st.session_state.notas = pd.concat([st.session_state.notas, df_notas_debito_importado], ignore_index=True)
                save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE)
                st.session_state.data_imported = True

            if st.session_state.data_imported:
                st.success("Datos importados correctamente. Recalculando saldos...")
            else:
                st.info("No se importaron datos válidos de ninguna hoja.")

    except Exception as e:
        st.error(f"Error al cargar o procesar el archivo Excel: {e}")
        st.exception(e)


def add_debit_note(fecha_nota, descuento, descuento_real):
    """Agrega una nueva nota de débito."""
    df_data = st.session_state.data.copy()
    
    # Validar que existan libras restantes para la fecha y calcular libras_calculadas
    df_data["Libras Restantes"] = pd.to_numeric(df_data["Libras Restantes"], errors='coerce').fillna(0)
    
    # Excluir la fila de BALANCE_INICIAL del cálculo de libras
    libras_calculadas = df_data[
        (df_data["Fecha"] == fecha_nota) & 
        (df_data["Proveedor"] != "BALANCE_INICIAL")
    ]["Libras Restantes"].sum()
    
    descuento_posible = libras_calculadas * descuento
    
    nueva_nota = {
        "Fecha": fecha_nota,
        "Libras calculadas": libras_calculadas,
        "Descuento": float(descuento),
        "Descuento posible": descuento_posible,
        "Descuento real": float(descuento_real)
    }
    st.session_state.notas = pd.concat([st.session_state.notas, pd.DataFrame([nueva_nota])], ignore_index=True)
    if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
        st.session_state.debit_note_added = True
        st.success("Nota de debito agregada correctamente. Recalculando saldos...")
    else:
        st.error("Error al guardar la nota de débito.")

def delete_debit_note_record(index_to_delete):
    """Elimina una nota de débito seleccionada por su índice real."""
    try:
        st.session_state.notas = st.session_state.notas.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
            st.session_state.debit_note_deleted = True
            st.success("Nota de debito eliminada correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar la nota de débito.")
    except IndexError:
        st.error("Índice de nota de débito no válido para eliminar.")
    except KeyError:
        st.error("El índice de nota de débito seleccionado ya no existe.")

def edit_debit_note_record(index_to_edit, updated_data):
    """Edita una nota de débito por su índice real en el DataFrame."""
    try:
        current_df = st.session_state.notas.copy()

        if index_to_edit not in current_df.index:
            st.error("El índice de nota de débito a editar no es válido o ya no existe.")
            return

        for key, value in updated_data.items():
            if key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            elif key in ["Descuento", "Descuento real"]:
                current_df.loc[index_to_edit, key] = float(value)
            else:
                current_df.loc[index_to_edit, key] = value
        
        # Recalcular Descuento posible
        fecha_nota_actual = current_df.loc[index_to_edit, "Fecha"]
        descuento_actual = current_df.loc[index_to_edit, "Descuento"]

        df_data_for_calc = st.session_state.data.copy()
        df_data_for_calc["Libras Restantes"] = pd.to_numeric(df_data_for_calc["Libras Restantes"], errors='coerce').fillna(0)
        libras_calculadas_recalc = df_data_for_calc[
            (df_data_for_calc["Fecha"] == fecha_nota_actual) & 
            (df_data_for_calc["Proveedor"] != "BALANCE_INICIAL")
        ]["Libras Restantes"].sum()

        current_df.loc[index_to_edit, "Libras calculadas"] = libras_calculadas_recalc
        current_df.loc[index_to_edit, "Descuento posible"] = libras_calculadas_recalc * descuento_actual

        st.session_state.notas = current_df
        if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
            st.session_state.debit_note_edited = True
            st.success("Nota de débito editada exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios de la nota de débito.")
    except Exception as e:
        st.error(f"Error al editar la nota de débito: {e}")
        st.exception(e)

# --- 5. FUNCIONES DE INTERFAZ DE USUARIO (UI) ---

def render_deposit_registration_form():
    """Renderiza el formulario de registro de depósitos en el sidebar."""
    st.sidebar.header("📝 Registro de Depósitos")
    with st.sidebar.form("registro_deposito_form", clear_on_submit=True):
        fecha_d = st.date_input("Fecha del registro", value=datetime.today().date(), key="fecha_d_input_sidebar")
        empresa = st.selectbox("Empresa (Proveedor)", PROVEEDORES, key="empresa_select_sidebar")
        agencia = st.selectbox("Agencia", AGENCIAS, key="agencia_select_sidebar")
        monto = st.number_input("Monto ($)", min_value=0.0, format="%.2f", key="monto_input_sidebar")
        submit_d = st.form_submit_button("➕ Agregar Depósito")

        if submit_d:
            if monto <= 0:
                st.error("El monto del depósito debe ser mayor que cero.")
            else:
                add_deposit_record(fecha_d, empresa, agencia, monto)

def render_delete_deposit_section():
    """Renderiza la sección para eliminar depósitos en el sidebar."""
    st.sidebar.subheader("🗑️ Eliminar Depósito")
    if not st.session_state.df.empty:
        df_display_deposits = st.session_state.df.copy()
        
        # Crear una columna temporal para mostrar y seleccionar, incluyendo el índice
        df_display_deposits["Display"] = df_display_deposits.apply(
            lambda row: f"{row.name} - {row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        
        # Usar el índice real del DataFrame para eliminar
        # Asegurarse de que el selectbox solo se muestre si hay elementos.
        if not df_display_deposits["Display"].empty:
            deposito_seleccionado_info = st.sidebar.selectbox(
                "Selecciona un depósito a eliminar", 
                df_display_deposits["Display"], 
                key="delete_deposit_select"
            )
        else:
            deposito_seleccionado_info = None

        index_to_delete = None
        if deposito_seleccionado_info:
            try:
                index_to_delete = int(deposito_seleccionado_info.split(' - ')[0])
            except ValueError:
                index_to_delete = None

        if st.sidebar.button("🗑️ Eliminar depósito seleccionado", key="delete_deposit_button"):
            if index_to_delete is not None:
                # Añadir confirmación antes de eliminar
                if st.sidebar.checkbox("✅ Confirmar eliminación del depósito", key="confirm_delete_deposit_checkbox"):
                    delete_deposit_record(index_to_delete)
                else:
                    st.sidebar.warning("Por favor, marca la casilla para confirmar la eliminación.")
            else:
                st.sidebar.error("Por favor, selecciona un depósito válido para eliminar.")
    else:
        st.sidebar.info("No hay depósitos para eliminar.")

def render_edit_deposit_section():
    """Renderiza la sección para editar depósitos en el sidebar."""
    st.sidebar.subheader("✏️ Editar Depósito")
    if not st.session_state.df.empty:
        df_display_deposits = st.session_state.df.copy()
        df_display_deposits["Display"] = df_display_deposits.apply(
            lambda row: f"{row.name} - {row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        
        if not df_display_deposits["Display"].empty:
            deposito_seleccionado_info = st.sidebar.selectbox(
                "Selecciona un depósito para editar",
                df_display_deposits["Display"],
                key="edit_deposit_select"
            )
        else:
            deposito_seleccionado_info = None

        index_to_edit = None
        if deposito_seleccionado_info:
            try:
                index_to_edit = int(deposito_seleccionado_info.split(' - ')[0])
            except ValueError:
                index_to_edit = None

        if index_to_edit is not None and index_to_edit in st.session_state.df.index:
            deposit_to_edit = st.session_state.df.loc[index_to_edit].to_dict()

            with st.sidebar.form(f"edit_deposit_form_{index_to_edit}", clear_on_submit=False):
                st.write(f"Editando depósito: **ID {index_to_edit}**")
                
                # Asegurar que los valores por defecto existan en las listas de opciones
                default_empresa_idx = PROVEEDORES.index(deposit_to_edit["Empresa"]) if deposit_to_edit["Empresa"] in PROVEEDORES else 0
                default_agencia_idx = AGENCIAS.index(deposit_to_edit["Agencia"]) if deposit_to_edit["Agencia"] in AGENCIAS else 0

                edited_fecha = st.date_input("Fecha", value=deposit_to_edit["Fecha"], key=f"edit_fecha_d_{index_to_edit}")
                edited_empresa = st.selectbox("Empresa (Proveedor)", PROVEEDORES, index=default_empresa_idx, key=f"edit_empresa_{index_to_edit}")
                edited_agencia = st.selectbox("Agencia", AGENCIAS, index=default_agencia_idx, key=f"edit_agencia_{index_to_edit}")
                edited_monto = st.number_input("Monto ($)", value=float(deposit_to_edit["Monto"]), min_value=0.0, format="%.2f", key=f"edit_monto_{index_to_edit}")
                
                submit_edit_deposit = st.form_submit_button("💾 Guardar Cambios del Depósito")

                if submit_edit_deposit:
                    if edited_monto <= 0:
                        st.error("El monto del depósito debe ser mayor que cero.")
                    else:
                        updated_data = {
                            "Fecha": edited_fecha,
                            "Empresa": edited_empresa,
                            "Agencia": edited_agencia,
                            "Monto": edited_monto
                        }
                        edit_deposit_record(index_to_edit, updated_data)
        else:
            st.sidebar.info("Selecciona un depósito para ver sus detalles de edición.")
    else:
        st.sidebar.info("No hay depósitos para editar.")


def render_import_excel_section():
    """Renderiza la sección para importar datos desde Excel."""
    st.subheader("📁 Importar datos desde Excel")
    st.info("Asegúrate de que tu archivo Excel tenga las siguientes hojas y columnas (con nombres exactos):")
    st.markdown("- **Hoja 1 (registro de proveedores):** `Fecha`, `Proveedor`, `Cantidad`, `Peso Salida (kg)`, `Peso Entrada (kg)`, `Tipo Documento`, `Cantidad de gavetas`, `Precio Unitario ($)`")
    st.markdown("- **Hoja 2 (registro de depositos):** `Fecha`, `Empresa`, `Agencia`, `Monto`")
    st.markdown("- **Hoja 3 (registro de notas de debito):** `Fecha`, `Descuento`, `Descuento real`")
    
    archivo_excel = st.file_uploader("Sube tu archivo Excel (.xlsx)", type=["xlsx"], key="excel_uploader")
    if archivo_excel is not None:
        import_excel_data(archivo_excel)

def render_supplier_registration_form():
    """Renderiza el formulario de registro de proveedores."""
    st.subheader("➕ Registro de Proveedores")
    with st.form("formulario_registro_proveedor", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha = st.date_input("Fecha", value=datetime.today().date(), key="fecha_input_form")
            proveedor = st.selectbox("Proveedor", PROVEEDORES, key="proveedor_select_form")
        with col2:
            cantidad = st.number_input("Cantidad", min_value=0, step=1, key="cantidad_input_form")
            peso_salida = st.number_input("Peso Salida (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_salida_input_form")
        with col3:
            peso_entrada = st.number_input("Peso Entrada (kg)", min_value=0.0, step=0.1, format="%.2f", key="peso_entrada_input_form")
            documento = st.selectbox("Tipo Documento", TIPOS_DOCUMENTO, key="documento_select_form")
        with col4:
            gavetas = st.number_input("Cantidad de gavetas", min_value=0, step=1, key="gavetas_input_form")
            precio_unitario = st.number_input("Precio Unitario ($)", min_value=0.0, step=0.01, format="%.2f", key="precio_unitario_input_form")

        enviar = st.form_submit_button("➕ Agregar Registro")

        if enviar:
            add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, documento, gavetas, precio_unitario)

def render_debit_note_form():
    """Renderiza el formulario para agregar notas de débito."""
    st.subheader("📝 Registro de Nota de Débito")
    with st.form("nota_debito_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            fecha_nota = st.date_input("Fecha de Nota", value=datetime.today().date(), key="fecha_nota_input_form")
        with col2:
            descuento = st.number_input("Descuento (%) (ej. 0.05 para 5%)", min_value=0.0, max_value=1.0, step=0.01, format="%.2f", value=0.0, key="descuento_input_form")
        with col3:
            descuento_real = st.number_input("Descuento Real ($)", min_value=0.0, step=0.01, format="%.2f", value=0.0, key="descuento_real_input_form")
        
        agregar_nota = st.form_submit_button("➕ Agregar Nota de Débito")

        if agregar_nota:
            if descuento_real <= 0 and descuento <= 0:
                st.error("Debes ingresar un valor para Descuento (%) o Descuento Real ($) mayor que cero.")
            else:
                add_debit_note(fecha_nota, descuento, descuento_real)

def render_delete_debit_note_section():
    """Renderiza la sección para eliminar notas de débito."""
    st.subheader("🗑️ Eliminar Nota de Débito")
    if not st.session_state.notas.empty:
        df_display_notes = st.session_state.notas.copy()
        df_display_notes["Display"] = df_display_notes.apply(
            lambda row: f"{row.name} - {row['Fecha']} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        
        if not df_display_notes["Display"].empty:
            nota_seleccionada_info = st.selectbox(
                "Selecciona una nota de débito para eliminar", 
                df_display_notes["Display"], 
                key="delete_debit_note_select"
            )
        else:
            nota_seleccionada_info = None

        index_to_delete = None
        if nota_seleccionada_info:
            try:
                index_to_delete = int(nota_seleccionada_info.split(' - ')[0])
            except ValueError:
                index_to_delete = None
        
        if st.button("🗑️ Eliminar Nota de Débito seleccionada", key="delete_debit_note_button"):
            if index_to_delete is not None:
                if st.checkbox("✅ Confirmar eliminación de la nota de débito", key="confirm_delete_debit_note"):
                    delete_debit_note_record(index_to_delete)
                else:
                    st.warning("Por favor, marca la casilla para confirmar la eliminación.")
            else:
                st.error("Por favor, selecciona una nota de débito válida para eliminar.")
    else:
        st.info("No hay notas de débito para eliminar.")

def render_edit_debit_note_section():
    """Renderiza la sección para editar notas de débito."""
    st.subheader("✏️ Editar Nota de Débito")
    if not st.session_state.notas.empty:
        df_display_notes = st.session_state.notas.copy()
        df_display_notes["Display"] = df_display_notes.apply(
            lambda row: f"{row.name} - {row['Fecha']} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        
        if not df_display_notes["Display"].empty:
            nota_seleccionada_info = st.selectbox(
                "Selecciona una nota de débito para editar",
                df_display_notes["Display"],
                key="edit_debit_note_select"
            )
        else:
            nota_seleccionada_info = None


        index_to_edit = None
        if nota_seleccionada_info:
            try:
                index_to_edit = int(nota_seleccionada_info.split(' - ')[0])
            except ValueError:
                index_to_edit = None

        if index_to_edit is not None and index_to_edit in st.session_state.notas.index:
            note_to_edit = st.session_state.notas.loc[index_to_edit].to_dict()

            with st.form(f"edit_debit_note_form_{index_to_edit}", clear_on_submit=False):
                st.write(f"Editando nota de débito: **ID {index_to_edit}**")
                edited_fecha_nota = st.date_input("Fecha de Nota", value=note_to_edit["Fecha"], key=f"edit_fecha_nota_{index_to_edit}")
                edited_descuento = st.number_input("Descuento (%) (ej. 0.05 para 5%)", value=float(note_to_edit["Descuento"]), min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key=f"edit_descuento_{index_to_edit}")
                edited_descuento_real = st.number_input("Descuento Real ($)", value=float(note_to_edit["Descuento real"]), min_value=0.0, step=0.01, format="%.2f", key=f"edit_descuento_real_{index_to_edit}")
                
                submit_edit_note = st.form_submit_button("💾 Guardar Cambios de Nota de Débito")

                if submit_edit_note:
                    if edited_descuento_real <= 0 and edited_descuento <= 0:
                        st.error("Debes ingresar un valor para Descuento (%) o Descuento Real ($) mayor que cero.")
                    else:
                        updated_data = {
                            "Fecha": edited_fecha_nota,
                            "Descuento": edited_descuento,
                            "Descuento real": edited_descuento_real
                        }
                        edit_debit_note_record(index_to_edit, updated_data)
        else:
            st.info("Selecciona una nota de débito para ver sus detalles de edición.")
    else:
        st.info("No hay notas de débito para editar.")


def display_formatted_dataframe(df_source, title, columns_to_format=None, key_suffix="", editable_cols=None):
    """Muestra un DataFrame con formato de moneda y capacidad de edición."""
    st.subheader(title)
    
    df_display = df_source.copy()

    # Formatear columnas numéricas para visualización (solo string para display)
    if columns_to_format:
        for col in columns_to_format:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
                df_display[col] = df_display[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    
    # Convertir las columnas de fecha a string con un formato específico para mostrar en la tabla.
    # st.dataframe editable maneja la conversión de vuelta a tipo nativo después de la edición.
    if "Fecha" in df_display.columns:
        df_display["Fecha"] = df_display["Fecha"].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else "")


    # Definir las configuraciones de edición
    column_config = {}
    if editable_cols:
        for col_name, col_type in editable_cols.items():
            if col_type == "text":
                column_config[col_name] = st.column_config.TextColumn(col_name)
            elif col_type == "number":
                column_config[col_name] = st.column_config.NumberColumn(col_name, format="%.2f")
            elif col_type == "date":
                column_config[col_name] = st.column_config.DateColumn(col_name, format="YYYY-MM-DD")
            elif col_type == "selectbox_proveedores":
                column_config[col_name] = st.column_config.SelectboxColumn(col_name, options=PROVEEDORES)
            elif col_type == "selectbox_documento":
                column_config[col_name] = st.column_config.SelectboxColumn(col_name, options=TIPOS_DOCUMENTO)
            elif col_type == "selectbox_agencias":
                column_config[col_name] = st.column_config.SelectboxColumn(col_name, options=AGENCIAS)
            elif col_type == "number_int":
                column_config[col_name] = st.column_config.NumberColumn(col_name, format="%d", step=1)
            
    # Mostrar el DataFrame con capacidad de edición
    # No es necesario convertir todo a string antes de st.dataframe, ya que column_config maneja los tipos
    edited_df = st.dataframe(
        df_display, 
        use_container_width=True, 
        key=f"editable_df_{key_suffix}", 
        hide_index=False, # Mostrar el índice para facilitar la identificación de filas
        column_config=column_config
    )

    # Manejar las ediciones
    # El error KeyError ocurre aquí si "edited_rows" no existe.
    # Se debe verificar si la clave existe antes de intentar acceder a ella.
    if f"editable_df_{key_suffix}" in st.session_state and st.session_state[f"editable_df_{key_suffix}"]["edited_rows"]:
        st.info("¡Se han detectado cambios en la tabla! Presiona 'Guardar Cambios' para aplicar.")
        if st.button(f"💾 Guardar Cambios en {title}", key=f"save_changes_{key_suffix}"):
            try:
                # Obtener el DataFrame editado directamente desde st.dataframe
                df_updated_rows = st.session_state[f"editable_df_{key_suffix}"]["edited_rows"]
                
                original_df_to_update = df_source.copy()

                # Iterar sobre las filas editadas y aplicar los cambios
                for idx_str, changes in df_updated_rows.items():
                    idx = int(idx_str) # Convertir el índice a entero

                    # Ignorar la fila de BALANCE_INICIAL si se está editando la tabla de registros
                    if title == "Tabla de Registros" and original_df_to_update.loc[idx, "Proveedor"] == "BALANCE_INICIAL":
                        st.warning(f"No se pueden editar las propiedades de la fila de BALANCE_INICIAL (ID: {idx}).")
                        continue

                    for col, value in changes.items():
                        # Convertir el valor al tipo de dato original de la columna
                        original_type = df_source[col].dtype
                        if pd.api.types.is_datetime64_any_dtype(original_type) or isinstance(df_source.loc[idx, col], (date, datetime)):
                            try:
                                original_df_to_update.loc[idx, col] = pd.to_datetime(value).date()
                            except (ValueError, TypeError): # Atrapar tanto ValueError como TypeError
                                st.warning(f"Formato de fecha inválido para la columna '{col}' en la fila {idx}. Se mantendrá el valor anterior.")
                                original_df_to_update.loc[idx, col] = df_source.loc[idx, col] # Revertir al valor original
                        elif pd.api.types.is_numeric_dtype(original_type):
                            try:
                                if editable_cols and editable_cols.get(col) == "number_int":
                                    original_df_to_update.loc[idx, col] = int(value)
                                else:
                                    original_df_to_update.loc[idx, col] = float(value)
                            except (ValueError, TypeError): # Atrapar tanto ValueError como TypeError
                                st.warning(f"Valor numérico inválido para la columna '{col}' en la fila {idx}. Se mantendrá el valor anterior.")
                                original_df_to_update.loc[idx, col] = df_source.loc[idx, col] # Revertir al valor original
                        else:
                            original_df_to_update.loc[idx, col] = value
                
                # Actualizar el DataFrame en session state
                if title == "Tabla de Registros":
                    st.session_state.data = original_df_to_update
                    if save_dataframe(st.session_state.data, DATA_FILE):
                        st.session_state.record_edited = True
                        st.success(f"Cambios en {title} guardados exitosamente. Recalculando saldos...")
                    else:
                        st.error(f"Error al guardar los cambios en {title}.")
                elif title == "Depósitos Registrados":
                    st.session_state.df = original_df_to_update
                    if save_dataframe(st.session_state.df, DEPOSITS_FILE):
                        st.session_state.deposit_edited = True
                        st.success(f"Cambios en {title} guardados exitosamente. Recalculando saldos...")
                    else:
                        st.error(f"Error al guardar los cambios en {title}.")
                elif title == "Tabla de Notas de Débito":
                    st.session_state.notas = original_df_to_update
                    if save_dataframe(st.session_state.notas, DEBIT_NOTES_FILE):
                        st.session_state.debit_note_edited = True
                        st.success(f"Cambios en {title} guardados exitosamente. Recalculando saldos...")
                    else:
                        st.error(f"Error al guardar los cambios en {title}.")
                
            except Exception as e:
                st.error(f"Error al procesar los cambios en la tabla: {e}")
                st.exception(e) # Para depuración

def render_tables_and_download():
    """Renderiza las tablas de registros, notas de débito y la opción de descarga."""
    
    # Tabla de Registros
    df_display_data = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
    
    editable_cols_data = {
        "Fecha": "date",
        "Proveedor": "selectbox_proveedores",
        "Cantidad": "number_int",
        "Peso Salida (kg)": "number",
        "Peso Entrada (kg)": "number",
        "Tipo Documento": "selectbox_documento",
        "Cantidad de gavetas": "number_int",
        "Precio Unitario ($)": "number"
    }

    if not df_display_data.empty:
        display_formatted_dataframe(
            df_display_data,
            "Tabla de Registros",
            columns_to_format=["Total ($)", "Monto Deposito", "Saldo diario", "Saldo Acumulado", "Precio Unitario ($)"],
            key_suffix="main_records",
            editable_cols=editable_cols_data
        )
        st.subheader("🗑️ Eliminar un Registro")
        # Usar el índice real del DataFrame para eliminar
        df_display_data_for_del = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
        
        if not df_display_data_for_del.empty:
            df_display_data_for_del["Display"] = df_display_data_for_del.apply(
                lambda row: f"{row.name} - {row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}"
                if pd.notna(row["Total ($)"]) else f"{row.name} - {row['Fecha']} - {row['Proveedor']} - Sin total",
                axis=1
            )

            registro_seleccionado_info = st.selectbox(
                "Selecciona un registro para eliminar", df_display_data_for_del["Display"], key="delete_record_select"
            )
            index_to_delete_record = None
            if registro_seleccionado_info:
                try:
                    index_to_delete_record = int(registro_seleccionado_info.split(' - ')[0])
                except ValueError:
                    index_to_delete_record = None

            if st.button("🗑️ Eliminar Registro Seleccionado", key="delete_record_button"):
                if index_to_delete_record is not None:
                    if st.checkbox("✅ Confirmar eliminación del registro", key="confirm_delete_record"):
                        delete_record(index_to_delete_record)
                    else:
                        st.warning("Por favor, marca la casilla para confirmar la eliminación.")
                else:
                    st.error("Por favor, selecciona un registro válido para eliminar.")
        else:
            st.info("No hay registros disponibles para eliminar.")
    else:
        st.subheader("Tabla de Registros")
        st.info("No hay registros disponibles. Por favor, agrega algunos o importa desde Excel.")

    st.markdown("---") # Separador visual

    # Tabla de Notas de Débito
    editable_cols_notes = {
        "Fecha": "date",
        "Descuento": "number", # Representa el porcentaje, no el real
        "Descuento real": "number"
    }

    if not st.session_state.notas.empty:
        display_formatted_dataframe(
            st.session_state.notas,
            "Tabla de Notas de Débito",
            columns_to_format=["Descuento posible", "Descuento real"],
            key_suffix="debit_notes",
            editable_cols=editable_cols_notes
        )
        render_delete_debit_note_section()
        render_edit_debit_note_section() # Incluir la sección de edición aquí
    else:
        st.subheader("Tabla de Notas de Débito")
        st.info("No hay notas de débito registradas.")

    st.markdown("---") # Separador visual

    with st.expander("Ver y Editar Depósitos Registrados"):
        editable_cols_deposits = {
            "Fecha": "date",
            "Empresa": "selectbox_proveedores",
            "Agencia": "selectbox_agencias",
            "Monto": "number"
        }
        if not st.session_state.df.empty:
            display_formatted_dataframe(
                st.session_state.df,
                "Depósitos Registrados",
                columns_to_format=["Monto"],
                key_suffix="deposits",
                editable_cols=editable_cols_deposits
            )
            # Los botones de eliminar y editar para depósitos ya están en el sidebar
        else:
            st.info("No hay depósitos registrados.")

    st.markdown("---") # Separador visual

    # Sección de Descarga de Excel
    @st.cache_data
    def convertir_excel(df_data, df_deposits, df_notes):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # Filtrar la fila de BALANCE_INICIAL para la exportación si no se desea
            df_data_export = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()
            
            # Limpiar columnas temporales o de display antes de exportar
            # No es necesario si se maneja bien la creación de la columna "Display" dentro de las funciones
            # pero como seguridad, podemos verificar si existen.
            if "Display" in df_data_export.columns:
                df_data_export = df_data_export.drop(columns=["Display"])
            
            if "Display" in df_deposits.columns:
                df_deposits = df_deposits.drop(columns=["Display"])
            
            if "Display" in df_notes.columns:
                df_notes = df_notes.drop(columns=["Display"])

            df_data_export.to_excel(writer, sheet_name="registro de proveedores", index=False)
            df_deposits.to_excel(writer, sheet_name="registro de depositos", index=False)
            df_notes.to_excel(writer, sheet_name="registro de notas de debito", index=False)
        output.seek(0)
        return output

    if not st.session_state.data.empty or not st.session_state.df.empty or not st.session_state.notas.empty:
        st.download_button(
            label="⬇️ Descargar Todos los Datos en Excel",
            data=convertir_excel(st.session_state.data, st.session_state.df, st.session_state.notas),
            file_name="registro_completo_proveedores_depositos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descarga todas las tablas de registros, depósitos y notas de débito en un solo archivo Excel."
        )

# Función para imprimir reportes y gráficos
def get_image_as_base64(fig):
    """Convierte una figura de Matplotlib a base64 para incrustarla en PDF."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode()
    plt.close(fig) # Cerrar la figura para liberar memoria
    return img_base64

def generate_pdf_report(title, content_elements, filename="reporte.pdf"):
    """Genera un PDF con el título y elementos de contenido dados."""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{title}</b>", styles['h1']))
    story.append(Spacer(1, 0.2 * inch))

    for element in content_elements:
        story.append(element)
        story.append(Spacer(1, 0.1 * inch)) # Espacio entre elementos

    try:
        doc.build(story)
        with open(filename, "rb") as f:
            pdf_bytes = f.read()
        
        st.download_button(
            label=f"🖨️ Imprimir {title} (PDF)",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            key=f"print_button_{filename.replace('.', '_')}"
        )
    except Exception as e:
        st.error(f"Error al generar el PDF: {e}")
        st.exception(e) # Para depuración

def create_table_for_pdf(df, title, columns_to_format=None):
    """Crea un objeto Table de ReportLab a partir de un DataFrame."""
    if df.empty:
        return Paragraph(f"No hay datos para '{title}'.", getSampleStyleSheet()['Normal'])

    # Prepare data for ReportLab table
    # Drop "Display" column if it exists, as it's for Streamlit's selectbox
    df_pdf = df.copy()
    if "Display" in df_pdf.columns:
        df_pdf = df_pdf.drop(columns=["Display"])

    # Formatear columnas numéricas para el PDF
    if columns_to_format:
        for col in columns_to_format:
            if col in df_pdf.columns:
                df_pdf[col] = pd.to_numeric(df_pdf[col], errors='coerce')
                df_pdf[col] = df_pdf[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    
    # Asegurarse de que todas las celdas sean strings para ReportLab
    data = [df_pdf.columns.tolist()] + df_pdf.values.astype(str).tolist()

    table = Table(data)

    # Estilos básicos de la tabla
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#004d40')), # Fondo de la cabecera
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), # Color de texto de la cabecera
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige), # Fondo de las filas
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 8), # Reduce el tamaño de la fuente para que quepa más
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    return table

def render_weekly_report():
    """Renderiza el reporte semanal y añade botón de impresión."""
    st.header("📈 Reporte Semanal")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    content_elements = []

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)
        
        if not df.empty:
            df["YearWeek"] = df["Fecha"].dt.strftime('%Y-%U')
            if not df["YearWeek"].empty:
                semana_actual = df["YearWeek"].max()
                df_semana = df[df["YearWeek"] == semana_actual].drop(columns=["YearWeek"])
                
                if not df_semana.empty:
                    st.subheader(f"Registros de la Semana {semana_actual}")
                    st.dataframe(
                        df_semana.style.format({
                            "Total ($)": "${:,.2f}", 
                            "Monto Deposito": "${:,.2f}", 
                            "Saldo diario": "${:,.2f}", 
                            "Saldo Acumulado": "${:,.2f}",
                            "Precio Unitario ($)": "${:,.2f}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                    content_elements.append(Paragraph(f"<b>Registros de la Semana {semana_actual}</b>", getSampleStyleSheet()['h2']))
                    content_elements.append(create_table_for_pdf(df_semana, "Registros Semanales", columns_to_format=["Total ($)", "Monto Deposito", "Saldo diario", "Saldo Acumulado", "Precio Unitario ($)"]))

                else:
                    st.info(f"No hay datos para la semana actual ({semana_actual}).")
                    content_elements.append(Paragraph(f"No hay datos para la semana actual ({semana_actual}).", getSampleStyleSheet()['Normal']))
            else:
                st.info("No hay datos con fecha válida para generar el reporte semanal.")
                content_elements.append(Paragraph("No hay datos con fecha válida para generar el reporte semanal.", getSampleStyleSheet()['Normal']))
        else:
            st.info("No hay datos para generar el reporte semanal después de filtrar fechas no válidas.")
            content_elements.append(Paragraph("No hay datos para generar el reporte semanal después de filtrar fechas no válidas.", getSampleStyleSheet()['Normal']))
    else:
        st.info("No hay datos para generar el reporte semanal.")
        content_elements.append(Paragraph("No hay datos para generar el reporte semanal.", getSampleStyleSheet()['Normal']))

    # Botón de impresión
    if st.button("🖨️ Imprimir Reporte Semanal", key="print_weekly_report"):
        generate_pdf_report("Reporte Semanal de Proveedores", content_elements, "reporte_semanal.pdf")

def render_monthly_report():
    """Renderiza el reporte mensual y añade botón de impresión."""
    st.header("📊 Reporte Mensual")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    content_elements = []

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)

        if not df.empty:
            mes_actual = datetime.today().month
            año_actual = datetime.today().year
            df_mes = df[(df["Fecha"].dt.month == mes_actual) & (df["Fecha"].dt.year == año_actual)]
            
            if not df_mes.empty:
                st.subheader(f"Registros del Mes {mes_actual}/{año_actual}")
                st.dataframe(
                    df_mes.style.format({
                        "Total ($)": "${:,.2f}", 
                        "Monto Deposito": "${:,.2f}", 
                        "Saldo diario": "${:,.2f}", 
                        "Saldo Acumulado": "${:,.2f}",
                        "Precio Unitario ($)": "${:,.2f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )
                content_elements.append(Paragraph(f"<b>Registros del Mes {mes_actual}/{año_actual}</b>", getSampleStyleSheet()['h2']))
                content_elements.append(create_table_for_pdf(df_mes, "Registros Mensuales", columns_to_format=["Total ($)", "Monto Deposito", "Saldo diario", "Saldo Acumulado", "Precio Unitario ($)"]))

            else:
                st.info(f"No hay datos para el mes actual ({mes_actual}/{año_actual}).")
                content_elements.append(Paragraph(f"No hay datos para el mes actual ({mes_actual}/{año_actual}).", getSampleStyleSheet()['Normal']))
        else:
            st.info("No hay datos para generar el reporte mensual después de filtrar fechas no válidas.")
            content_elements.append(Paragraph("No hay datos para generar el reporte mensual después de filtrar fechas no válidas.", getSampleStyleSheet()['Normal']))
    else:
        st.info("No hay datos para generar el reporte mensual.")
        content_elements.append(Paragraph("No hay datos para generar el reporte mensual.", getSampleStyleSheet()['Normal']))
    
    # Botón de impresión
    if st.button("🖨️ Imprimir Reporte Mensual", key="print_monthly_report"):
        generate_pdf_report("Reporte Mensual de Proveedores", content_elements, "reporte_mensual.pdf")

def render_charts():
    """Renderiza los gráficos de datos y añade botón de impresión."""
    st.header("📊 Gráficos de Proveedores y Saldo")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()

    content_elements = []

    if df.empty:
        st.info("No hay datos suficientes para generar gráficos. Por favor, agregue registros.")
        return

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df.dropna(subset=["Fecha"], inplace=True)

    # Gráfico 1: Total por Proveedor
    st.subheader("Total por Proveedor")
    df["Total ($)"] = pd.to_numeric(df["Total ($)"], errors='coerce').fillna(0)
    total_por_proveedor = df.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
    
    fig_proveedores = None
    if not total_por_proveedor.empty and total_por_proveedor.sum() > 0:
        fig_proveedores, ax = plt.subplots(figsize=(10, 6))
        total_por_proveedor.plot(kind="bar", ax=ax, color='skyblue')
        ax.set_ylabel("Total ($)")
        ax.set_title("Total ($) por Proveedor")
        ax.ticklabel_format(style='plain', axis='y')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig_proveedores)
        content_elements.append(Paragraph("<b>Total por Proveedor</b>", getSampleStyleSheet()['h2']))
        content_elements.append(RImage(BytesIO(base64.b64decode(get_image_as_base64(fig_proveedores))), width=5*inch, height=3*inch))
    else:
        st.info("No hay datos de 'Total ($)' por proveedor para graficar o todos son cero.")
        content_elements.append(Paragraph("No hay datos de 'Total ($)' por proveedor para graficar o todos son cero.", getSampleStyleSheet()['Normal']))
    
    # Gráfico 2: Evolución del Saldo Acumulado
    st.subheader("Evolución del Saldo Acumulado")
    df_ordenado = df.sort_values("Fecha")
    df_ordenado["Saldo Acumulado"] = pd.to_numeric(df_ordenado["Saldo Acumulado"], errors='coerce').fillna(INITIAL_ACCUMULATED_BALANCE)
    
    df_ordenado = df_ordenado[df_ordenado['Fecha'].notna()]

    fig_saldo = None
    if not df_ordenado.empty:
        # Para graficar, tomemos el último saldo acumulado de cada día.
        daily_last_saldo = df_ordenado.groupby("Fecha")["Saldo Acumulado"].last().reset_index()

        fig_saldo, ax2 = plt.subplots(figsize=(12, 6))
        ax2.plot(daily_last_saldo["Fecha"], daily_last_saldo["Saldo Acumulado"], marker="o", linestyle='-', color='green')
        ax2.set_ylabel("Saldo Acumulado ($)")
        ax2.set_title("Evolución del Saldo Acumulado")
        ax2.grid(True, linestyle='--', alpha=0.7)
        ax2.ticklabel_format(style='plain', axis='y')
        plt.xticks(rotation=45, ha='right')
        
        # Formatear el eje y como moneda
        formatter = mticker.FormatStrFormatter('$%.2f')
        ax2.yaxis.set_major_formatter(formatter)

        plt.tight_layout()
        st.pyplot(fig_saldo)
        content_elements.append(Paragraph("<b>Evolución del Saldo Acumulado</b>", getSampleStyleSheet()['h2']))
        content_elements.append(RImage(BytesIO(base64.b64decode(get_image_as_base64(fig_saldo))), width=6*inch, height=3*inch))
    else:
        st.info("No hay datos de 'Saldo Acumulado' para graficar.")
        content_elements.append(Paragraph("No hay datos de 'Saldo Acumulado' para graficar.", getSampleStyleSheet()['Normal']))

    # Botón de impresión para los gráficos
    if st.button("🖨️ Imprimir Gráficos (PDF)", key="print_charts_report"):
        generate_pdf_report("Gráficos de Proveedores y Saldo", content_elements, "graficos_proveedores.pdf")


# --- CONFIGURACIÓN PRINCIPAL DE LA PÁGINA ---
st.title("Sistema de Gestión de Proveedores - Producto Pollo")

# --- INICIALIZAR EL ESTADO DE LA SESIÓN ---
initialize_session_state()

# --- NAVEGACIÓN PRINCIPAL ---
st.sidebar.title("Menú Principal")
opcion = st.sidebar.selectbox("Selecciona una vista", ["Registro", "Reporte Semanal", "Reporte Mensual", "Gráficos"])

# --- RENDERIZAR SECCIONES SEGÚN LA OPCIÓN SELECCIONADA ---
if opcion == "Registro":
    st.sidebar.markdown("---")
    render_deposit_registration_form()
    render_delete_deposit_section()
    render_edit_deposit_section() # Nueva sección de edición de depósitos
    st.sidebar.markdown("---") # Separador visual

    render_import_excel_section()
    st.markdown("---")
    render_supplier_registration_form()
    st.markdown("---")
    render_debit_note_form()
    st.markdown("---") # Separador visual
    render_tables_and_download()

elif opcion == "Reporte Semanal":
    render_weekly_report()

elif opcion == "Reporte Mensual":
    render_monthly_report()

elif opcion == "Gráficos":
    render_charts()

# --- Manejo de reruns después de las operaciones ---
# Un solo chequeo para evitar múltiples reruns innecesarios
if st.session_state.deposit_added or st.session_state.deposit_deleted or \
   st.session_state.record_added or st.session_state.record_deleted or \
   st.session_state.data_imported or st.session_state.debit_note_added or \
   st.session_state.debit_note_deleted or st.session_state.record_edited or \
   st.session_state.deposit_edited or st.session_state.debit_note_edited:
    
    # Resetear todos los flags
    st.session_state.deposit_added = False
    st.session_state.deposit_deleted = False
    st.session_state.record_added = False
    st.session_state.record_deleted = False
    st.session_state.data_imported = False
    st.session_state.debit_note_added = False
    st.session_state.debit_note_deleted = False
    st.session_state.record_edited = False
    st.session_state.deposit_edited = False
    st.session_state.debit_note_edited = False
    
    recalculate_accumulated_balances()
    st.rerun()
