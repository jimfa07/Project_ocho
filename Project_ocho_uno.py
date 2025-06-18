import streamlit as st
import pandas as pd
from datetime import datetime, date
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
import base64
from supabase import create_client, Client
from st_supabase_connection import SupabaseConnection

# --- 1. CONSTANTES Y CONFIGURACIÓN INICIAL ---
INITIAL_ACCUMULATED_BALANCE = 176.01
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

# Columnas esperadas para los DataFrames (coinciden con las tablas en Supabase)
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

# --- 2. FUNCIONES DE CARGA Y GUARDADO DE DATOS CON SUPABASE ---
@st.cache_resource
def init_supabase():
    """Inicializa la conexión con Supabase."""
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        return conn
    except Exception as e:
        st.error(f"Error al conectar con Supabase: {e}")
        return None

def load_dataframe(table_name, default_columns, date_columns=None):
    """Carga un DataFrame desde una tabla de Supabase."""
    conn = st.session_state.conn
    if not conn:
        st.error("No se pudo establecer la conexión con Supabase.")
        return pd.DataFrame(columns=default_columns)

    try:
        response = conn.table(table_name).select("*").execute()
        df = pd.DataFrame(response.data)
        
        if df.empty:
            return pd.DataFrame(columns=default_columns)
        
        # Convertir columnas de fecha
        if date_columns:
            for col in date_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        
        # Asegurar que todas las columnas por defecto existen
        for col in default_columns:
            if col not in df.columns:
                df[col] = None
        
        return df[default_columns]
    except Exception as e:
        st.error(f"Error al cargar datos de {table_name}: {e}")
        return pd.DataFrame(columns=default_columns)

def save_dataframe(df, table_name):
    """Guarda un DataFrame en una tabla de Supabase."""
    conn = st.session_state.conn
    if not conn:
        st.error("No se pudo establecer la conexión con Supabase.")
        return False

    try:
        # Convertir DataFrame a lista de diccionarios
        data_list = df.to_dict("records")
        
        # Limpiar datos para evitar errores (por ejemplo, convertir fechas a string)
        for data in data_list:
            for key, value in data.items():
                if isinstance(value, (date, datetime)):
                    data[key] = value.strftime("%Y-%m-%d")
                elif pd.isna(value):
                    data[key] = None
        
        # Eliminar todos los registros existentes y reemplazar con los nuevos
        conn.table(table_name).delete().neq("id", -1).execute()  # Eliminar todo (neq evita error si tabla vacía)
        conn.table(table_name).insert(data_list).execute()
        return True
    except Exception as e:
        st.error(f"Error al guardar datos en {table_name}: {e}")
        return False

# --- 3. FUNCIONES DE INICIALIZACIÓN DEL ESTADO ---
def initialize_session_state():
    """Inicializa la conexión y los DataFrames en st.session_state."""
    if "conn" not in st.session_state:
        st.session_state.conn = init_supabase()
    
    if "data" not in st.session_state:
        st.session_state.data = load_dataframe("proveedores", COLUMNS_DATA, ["Fecha"])
        
        # Asegurar que la fila de balance inicial exista
        initial_balance_row_exists = any(st.session_state.data["Proveedor"] == "BALANCE_INICIAL")
        if not initial_balance_row_exists:
            fila_inicial_saldo = {col: None for col in COLUMNS_DATA}
            fila_inicial_saldo["Fecha"] = datetime(1900, 1, 1).date()
            fila_inicial_saldo["Proveedor"] = "BALANCE_INICIAL"
            fila_inicial_saldo["Saldo diario"] = 0.00
            fila_inicial_saldo["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE
            fila_inicial_saldo["Monto Deposito"] = 0.0
            fila_inicial_saldo["Total ($)"] = 0.0
            fila_inicial_saldo["N"] = "00"
            
            st.session_state.data = pd.concat([pd.DataFrame([fila_inicial_saldo]), st.session_state.data], ignore_index=True)
            save_dataframe(st.session_state.data, "proveedores")
    
    if "df" not in st.session_state:
        st.session_state.df = load_dataframe("depositos", COLUMNS_DEPOSITS, ["Fecha"])
        st.session_state.df["N"] = st.session_state.df["N"].astype(str)
    
    if "notas" not in st.session_state:
        st.session_state.notas = load_dataframe("notas_debito", COLUMNS_DEBIT_NOTES, ["Fecha"])
    
    recalculate_accumulated_balances()
    
    # Inicializar flags
    for flag in ["deposit_added", "deposit_deleted", "record_added", "record_deleted", 
                 "data_imported", "debit_note_added", "debit_note_deleted", 
                 "record_edited", "deposit_edited", "debit_note_edited"]:
        if flag not in st.session_state:
            st.session_state[flag] = False

# --- 4. FUNCIONES DE LÓGICA DE NEGOCIO Y CÁLCULOS ---
def recalculate_accumulated_balances():
    """Recalcula el Saldo Acumulado para los registros."""
    df_data = st.session_state.data.copy()
    df_deposits = st.session_state.df.copy()
    df_notes = st.session_state.notas.copy()

    for df_temp in [df_data, df_deposits, df_notes]:
        if "Fecha" in df_temp.columns:
            df_temp["Fecha"] = pd.to_datetime(df_temp["Fecha"], errors="coerce").dt.date

    df_initial_balance = df_data[df_data["Proveedor"] == "BALANCE_INICIAL"].copy()
    df_data_operaciones = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()

    numeric_cols_data = ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)", 
                        "Monto Deposito", "Total ($)", "Saldo diario", "Saldo Acumulado", 
                        "Kilos Restantes", "Libras Restantes", "Promedio", "Cantidad de gavetas"]
    for col in numeric_cols_data:
        if col in df_data_operaciones.columns:
            df_data_operaciones[col] = pd.to_numeric(df_data_operaciones[col], errors='coerce').fillna(0)

    if not df_data_operaciones.empty:
        df_data_operaciones["Kilos Restantes"] = df_data_operaciones["Peso Salida (kg)"] - df_data_operaciones["Peso Entrada (kg)"]
        df_data_operaciones["Libras Restantes"] = df_data_operaciones["Kilos Restantes"] * LBS_PER_KG
        df_data_operaciones["Promedio"] = df_data_operaciones.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
        df_data_operaciones["Total ($)"] = df_data_operaciones["Libras Restantes"] * df_data_operaciones["Precio Unitario ($)"]
    else:
        for col in ["Kilos Restantes", "Libras Restantes", "Promedio", "Total ($)"]:
            if col not in df_data_operaciones.columns:
                df_data_operaciones[col] = 0.0

    if not df_deposits.empty:
        df_deposits["Monto"] = pd.to_numeric(df_deposits["Monto"], errors='coerce').fillna(0)
        deposits_summary = df_deposits.groupby(["Fecha", "Empresa"])["Monto"].sum().reset_index()
        deposits_summary.rename(columns={"Monto": "Monto Deposito Calculado"}, inplace=True)

        df_data_operaciones["Empresa_key"] = df_data_operaciones["Proveedor"]
        df_data_operaciones = pd.merge(
            df_data_operaciones.drop(columns=["Monto Deposito"], errors='ignore'),
            deposits_summary,
            left_on=["Fecha", "Empresa_key"],
            right_on=["Fecha", "Empresa"],
            how="left"
        )
        df_data_operaciones["Monto Deposito"] = df_data_operaciones["Monto Deposito Calculado"].fillna(0)
        df_data_operaciones.drop(columns=["Monto Deposito Calculado", "Empresa", "Empresa_key"], inplace=True, errors='ignore')
    else:
        df_data_operaciones["Monto Deposito"] = 0.0

    df_data_operaciones["Saldo diario"] = df_data_operaciones["Monto Deposito"] - df_data_operaciones["Total ($)"]

    if not df_notes.empty:
        df_notes["Descuento real"] = pd.to_numeric(df_notes["Descuento real"], errors='coerce').fillna(0)
        notes_by_date = df_notes.groupby("Fecha")["Descuento real"].sum().reset_index()
        notes_by_date.rename(columns={"Descuento real": "NotaDebitoAjuste"}, inplace=True)
        
        daily_ops_saldo = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()
        full_daily_balances = pd.merge(daily_ops_saldo, notes_by_date, on="Fecha", how="left")
        full_daily_balances["NotaDebitoAjuste"] = full_daily_balances["NotaDebitoAjuste"].fillna(0)
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["Saldo diario"] + full_daily_balances["NotaDebitoAjuste"]
    else:
        full_daily_balances = df_data_operaciones.groupby("Fecha")["Saldo diario"].sum().reset_index()
        full_daily_balances["SaldoDiarioAjustado"] = full_daily_balances["Saldo diario"]
    
    full_daily_balances = full_daily_balances.sort_values("Fecha")
    full_daily_balances["Saldo Acumulado"] = INITIAL_ACCUMULATED_BALANCE + full_daily_balances["SaldoDiarioAjustado"].cumsum()

    saldo_diario_map = full_daily_balances.set_index("Fecha")["SaldoDiarioAjustado"].to_dict()
    saldo_acumulado_map = full_daily_balances.set_index("Fecha")["Saldo Acumulado"].to_dict()
    
    if not df_data_operaciones.empty:
        df_data_operaciones["Saldo diario"] = df_data_operaciones["Fecha"].map(saldo_diario_map).fillna(0)
        df_data_operaciones["Saldo Acumulado"] = df_data_operaciones["Fecha"].map(saldo_acumulado_map).fillna(INITIAL_ACCUMULATED_BALANCE)
    
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

    df_data = df_data[COLUMNS_DATA]
    df_data["N"] = df_data["N"].astype(str)
    df_data = df_data.sort_values(by=["Fecha", "N"], ascending=[True, True]).reset_index(drop=True)
    
    st.session_state.data = df_data
    save_dataframe(st.session_state.data, "proveedores")

def get_next_n(df, current_date):
    """Genera el siguiente número 'N' para un registro."""
    df_filtered = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    if not df_filtered.empty:
        df_filtered["N_numeric"] = pd.to_numeric(df_filtered["N"], errors='coerce').fillna(0)
        max_n_global = df_filtered["N_numeric"].max()
        return f"{int(max_n_global) + 1:02}"
    else:
        return "01"

def add_deposit_record(fecha_d, empresa, agencia, monto):
    """Agrega un nuevo registro de depósito."""
    df_actual = st.session_state.df.copy()
    df_actual["N"] = df_actual["N"].astype(str)

    if not df_actual.empty:
        valid_n_deposits = df_actual[df_actual["N"].str.isdigit()]["N"].astype(int)
        max_n_deposit = valid_n_deposits.max() if not valid_n_deposits.empty else 0
        numero = f"{max_n_deposit + 1:02}"
    else:
        numero = "01"

    documento = "Deposito" if "Cajero" in agencia else "Transferencia"
    
    nuevo_registro = {
        "Fecha": fecha_d,
        "Empresa": empresa,
        "Agencia": agencia,
        "Monto": float(monto),
        "Documento": documento,
        "N": numero
    }
    st.session_state.df = pd.concat([df_actual, pd.DataFrame([nuevo_registro])], ignore_index=True)
    if save_dataframe(st.session_state.df, "depositos"):
        st.session_state.deposit_added = True
        st.success("Depósito agregado exitosamente. Recalculando saldos...")
    else:
        st.error("Error al guardar el depósito.")

def delete_deposit_record(index_to_delete):
    """Elimina un registro de depósito."""
    try:
        st.session_state.df = st.session_state.df.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.df, "depositos"):
            st.session_state.deposit_deleted = True
            st.success("Depósito eliminado correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar el depósito.")
    except Exception as e:
        st.error(f"Error al eliminar el depósito: {e}")

def edit_deposit_record(index_to_edit, updated_data):
    """Edita un registro de depósito."""
    try:
        current_df = st.session_state.df.copy()
        if index_to_edit not in current_df.index:
            st.error("El índice de depósito no es válido.")
            return

        for key, value in updated_data.items():
            if key == "Monto":
                current_df.loc[index_to_edit, key] = float(value)
            elif key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            else:
                current_df.loc[index_to_edit, key] = value
        
        current_df.loc[index_to_edit, "Documento"] = "Deposito" if "Cajero" in str(updated_data.get("Agencia", current_df.loc[index_to_edit, "Agencia"])) else "Transferencia"

        st.session_state.df = current_df
        if save_dataframe(st.session_state.df, "depositos"):
            st.session_state.deposit_edited = True
            st.success("Depósito editado exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios del depósito.")
    except Exception as e:
        st.error(f"Error al editar el depósito: {e}")

def add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, tipo_documento, gavetas, precio_unitario):
    """Agrega un nuevo registro de proveedor."""
    df = st.session_state.data.copy()

    if not all(isinstance(val, (int, float)) and val >= 0 for val in [cantidad, peso_salida, peso_entrada, precio_unitario, gavetas]):
        st.error("Los valores numéricos no pueden ser negativos.")
        return False
    if cantidad == 0 and peso_salida == 0 and peso_entrada == 0:
        st.error("Ingresa una Cantidad y/o Pesos válidos.")
        return False
    if peso_entrada > peso_salida:
        st.error("El Peso Entrada no puede ser mayor que el Peso Salida.")
        return False

    kilos_restantes = peso_salida - peso_entrada
    libras_restantes = kilos_restantes * LBS_PER_KG
    promedio = libras_restantes / cantidad if cantidad != 0 else 0
    total = libras_restantes * precio_unitario

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
        "Monto Deposito": 0.0,
        "Saldo diario": 0.0,
        "Saldo Acumulado": 0.0
    }

    df_balance = df[df["Proveedor"] == "BALANCE_INICIAL"].copy()
    df_temp = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    df_temp = pd.concat([df_temp, pd.DataFrame([nueva_fila])], ignore_index=True)
    st.session_state.data = pd.concat([df_balance, df_temp], ignore_index=True)
    
    if save_dataframe(st.session_state.data, "proveedores"):
        st.session_state.record_added = True
        st.success("Registro agregado correctamente. Recalculando saldos...")
        return True
    else:
        st.error("Error al guardar el registro.")
        return False

def delete_record(index_to_delete):
    """Elimina un registro de la tabla principal."""
    try:
        if st.session_state.data.loc[index_to_delete, "Proveedor"] == "BALANCE_INICIAL":
            st.error("No se puede eliminar la fila de BALANCE_INICIAL.")
            return
        st.session_state.data = st.session_state.data.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.data, "proveedores"):
            st.session_state.record_deleted = True
            st.success("Registro eliminado correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar el registro.")
    except Exception as e:
        st.error(f"Error al eliminar el registro: {e}")

def edit_supplier_record(index_to_edit, updated_data):
    """Edita un registro de proveedor."""
    try:
        current_df = st.session_state.data.copy()
        if current_df.loc[index_to_edit, "Proveedor"] == "BALANCE_INICIAL":
            st.error("No se puede editar la fila de BALANCE_INICIAL.")
            return

        for key, value in updated_data.items():
            if key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            elif key in ["Cantidad", "Cantidad de gavetas"]:
                current_df.loc[index_to_edit, key] = int(value)
            elif key in ["Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)"]:
                current_df.loc[index_to_edit, key] = float(value)
            else:
                current_df.loc[index_to_edit, key] = value
        
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
        if save_dataframe(st.session_state.data, "proveedores"):
            st.session_state.record_edited = True
            st.success("Registro editado exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios del registro.")
    except Exception as e:
        st.error(f"Error al editar el registro: {e}")

def import_excel_data(archivo_excel):
    """Importa datos desde un archivo Excel y los guarda en Supabase."""
    try:
        xls = pd.ExcelFile(archivo_excel)
        sheet_names = xls.sheet_names
        
        # --- Hoja 1: Registro de Proveedores ---
        df_proveedores_importado = pd.DataFrame(columns=COLUMNS_DATA)
        if "registro de proveedores" in sheet_names:
            df_proveedores_importado = pd.read_excel(xls, sheet_name="registro de proveedores")
            st.write("Vista previa de **Registro de Proveedores**:", df_proveedores_importado.head())

            columnas_requeridas_proveedores = [
                "Fecha", "Proveedor", "Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)",
                "Tipo Documento", "Cantidad de gavetas", "Precio Unitario ($)"
            ]
            if not all(col in df_proveedores_importado.columns for col in columnas_requeridas_proveedores):
                st.warning(f"La hoja 'registro de proveedores' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_proveedores)}.")
            else:
                df_proveedores_importado["Fecha"] = pd.to_datetime(df_proveedores_importado["Fecha"], errors="coerce").dt.date
                df_proveedores_importado.dropna(subset=["Fecha"], inplace=True)

                for col in ["Cantidad", "Peso Salida (kg)", "Peso Entrada (kg)", "Precio Unitario ($)", "Cantidad de gavetas"]:
                    df_proveedores_importado[col] = pd.to_numeric(df_proveedores_importado[col], errors='coerce').fillna(0)
                
                df_proveedores_importado["Kilos Restantes"] = df_proveedores_importado["Peso Salida (kg)"] - df_proveedores_importado["Peso Entrada (kg)"]
                df_proveedores_importado["Libras Restantes"] = df_proveedores_importado["Kilos Restantes"] * LBS_PER_KG
                df_proveedores_importado["Promedio"] = df_proveedores_importado.apply(lambda row: row["Libras Restantes"] / row["Cantidad"] if row["Cantidad"] != 0 else 0, axis=1)
                df_proveedores_importado["Total ($)"] = df_proveedores_importado["Libras Restantes"] * df_proveedores_importado["Precio Unitario ($)"]
                
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
                df_proveedores_importado = df_proveedores_importado[COLUMNS_DATA]

        # --- Hoja 2: Registro de Depósitos ---
        df_depositos_importado = pd.DataFrame(columns=COLUMNS_DEPOSITS)
        if "registro de depositos" in sheet_names:
            df_depositos_importado = pd.read_excel(xls, sheet_name="registro de depositos")
            st.write("Vista previa de **Registro de Depósitos**:", df_depositos_importado.head())

            columnas_requeridas_depositos = ["Fecha", "Empresa", "Agencia", "Monto"]
            if not all(col in df_depositos_importado.columns for col in columnas_requeridas_depositos):
                st.warning(f"La hoja 'registro de depositos' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_depositos)}.")
            else:
                df_depositos_importado["Fecha"] = pd.to_datetime(df_depositos_importado["Fecha"], errors="coerce").dt.date
                df_depositos_importado.dropna(subset=["Fecha"], inplace=True)
                df_depositos_importado["Monto"] = pd.to_numeric(df_depositos_importado["Monto"], errors='coerce').fillna(0)
                
                current_deposits_data = st.session_state.df.copy()
                max_n_existing_deposits = 0
                if not current_deposits_data.empty:
                    valid_n_deposits = current_deposits_data[current_deposits_data["N"].str.isdigit()]["N"].astype(int)
                    max_n_existing_deposits = valid_n_deposits.max() if not valid_n_deposits.empty else 0
                
                new_n_counter_deposits = max_n_existing_deposits + 1
                df_depositos_importado["N"] = [f"{new_n_counter_deposits + i:02}" for i in range(len(df_depositos_importado))]
                df_depositos_importado["Documento"] = df_depositos_importado["Agencia"].apply(lambda x: "Deposito" if "Cajero" in str(x) else "Transferencia")
                df_depositos_importado = df_depositos_importado[COLUMNS_DEPOSITS]

        # --- Hoja 3: Registro de Notas de Débito ---
        df_notas_debito_importado = pd.DataFrame(columns=COLUMNS_DEBIT_NOTES)
        if "registro de notas de debito" in sheet_names:
            df_notas_debito_importado = pd.read_excel(xls, sheet_name="registro de notas de debito")
            st.write("Vista previa de **Registro de Notas de Débito**:", df_notas_debito_importado.head())

            columnas_requeridas_notas = ["Fecha", "Descuento", "Descuento real"]
            if not all(col in df_notas_debito_importado.columns for col in columnas_requeridas_notas):
                st.warning(f"La hoja 'registro de notas de debito' no contiene todas las columnas requeridas: {', '.join(columnas_requeridas_notas)}.")
            else:
                df_notas_debito_importado["Fecha"] = pd.to_datetime(df_notas_debito_importado["Fecha"], errors="coerce").dt.date
                df_notas_debito_importado.dropna(subset=["Fecha"], inplace=True)
                df_notas_debito_importado["Descuento"] = pd.to_numeric(df_notas_debito_importado["Descuento"], errors='coerce').fillna(0)
                df_notas_debito_importado["Descuento real"] = pd.to_numeric(df_notas_debito_importado["Descuento real"], errors='coerce').fillna(0)

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
                
                df_notas_debito_importado = df_notas_debito_importado[COLUMNS_DEBIT_NOTES]

        if st.button("Cargar datos a registros desde Excel"):
            if not df_proveedores_importado.empty:
                df_balance = st.session_state.data[st.session_state.data["Proveedor"] == "BALANCE_INICIAL"].copy()
                df_temp = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
                st.session_state.data = pd.concat([df_balance, df_temp, df_proveedores_importado], ignore_index=True)
                if save_dataframe(st.session_state.data, "proveedores"):
                    st.session_state.data_imported = True
                else:
                    st.error("Error al guardar proveedores en Supabase.")
            
            if not df_depositos_importado.empty:
                st.session_state.df = pd.concat([st.session_state.df, df_depositos_importado], ignore_index=True)
                st.session_state.df["N"] = st.session_state.df["N"].astype(str)
                if save_dataframe(st.session_state.df, "depositos"):
                    st.session_state.data_imported = True
                else:
                    st.error("Error al guardar depósitos en Supabase.")
            
            if not df_notas_debito_importado.empty:
                st.session_state.notas = pd.concat([st.session_state.notas, df_notas_debito_importado], ignore_index=True)
                if save_dataframe(st.session_state.notas, "notas_debito"):
                    st.session_state.data_imported = True
                else:
                    st.error("Error al guardar notas de débito en Supabase.")
            
            if st.session_state.data_imported:
                st.success("Datos importados y guardados en Supabase correctamente.")
                recalculate_accumulated_balances()
                st.rerun()
            else:
                st.info("No se importaron datos válidos.")

    except Exception as e:
        st.error(f"Error al cargar o procesar el archivo Excel: {e}")

def add_debit_note(fecha_nota, descuento, descuento_real):
    """Agrega una nueva nota de débito."""
    df_data = st.session_state.data.copy()
    df_data["Libras Restantes"] = pd.to_numeric(df_data["Libras Restantes"], errors='coerce').fillna(0)
    
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
    if save_dataframe(st.session_state.notas, "notas_debito"):
        st.session_state.debit_note_added = True
        st.success("Nota de débito agregada correctamente. Recalculando saldos...")
    else:
        st.error("Error al guardar la nota de débito.")

def delete_debit_note_record(index_to_delete):
    """Elimina una nota de débito."""
    try:
        st.session_state.notas = st.session_state.notas.drop(index=index_to_delete).reset_index(drop=True)
        if save_dataframe(st.session_state.notas, "notas_debito"):
            st.session_state.debit_note_deleted = True
            st.success("Nota de débito eliminada correctamente. Recalculando saldos...")
        else:
            st.error("Error al eliminar la nota de débito.")
    except Exception as e:
        st.error(f"Error al eliminar la nota de débito: {e}")

def edit_debit_note_record(index_to_edit, updated_data):
    """Edita una nota de débito."""
    try:
        current_df = st.session_state.notas.copy()
        if index_to_edit not in current_df.index:
            st.error("El índice de nota de débito no es válido.")
            return

        for key, value in updated_data.items():
            if key == "Fecha":
                current_df.loc[index_to_edit, key] = pd.to_datetime(value).date()
            elif key in ["Descuento", "Descuento real"]:
                current_df.loc[index_to_edit, key] = float(value)
            else:
                current_df.loc[index_to_edit, key] = value
        
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
        if save_dataframe(st.session_state.notas, "notas_debito"):
            st.session_state.debit_note_edited = True
            st.success("Nota de débito editada exitosamente. Recalculando saldos...")
        else:
            st.error("Error al guardar los cambios de la nota de débito.")
    except Exception as e:
        st.error(f"Error al editar la nota de débito: {e}")

# --- 5. FUNCIONES DE INTERFAZ DE USUARIO (UI) ---
def render_deposit_registration_form():
    """Formulario de registro de depósitos."""
    st.sidebar.header("📝 Registro de Depósitos")
    with st.sidebar.form("registro_deposito_form", clear_on_submit=True):
        fecha_d = st.date_input("Fecha del registro", value=datetime.today().date())
        empresa = st.selectbox("Empresa (Proveedor)", PROVEEDORES)
        agencia = st.selectbox("Agencia", AGENCIAS)
        monto = st.number_input("Monto ($)", min_value=0.0, format="%.2f")
        submit_d = st.form_submit_button("➕ Agregar Depósito")

        if submit_d:
            if monto <= 0:
                st.error("El monto del depósito debe ser mayor que cero.")
            else:
                add_deposit_record(fecha_d, empresa, agencia, monto)

def render_delete_deposit_section():
    """Sección para eliminar depósitos."""
    st.sidebar.subheader("🗑️ Eliminar Depósito")
    if not st.session_state.df.empty:
        df_display_deposits = st.session_state.df.copy()
        df_display_deposits["Display"] = df_display_deposits.apply(
            lambda row: f"{row.name} - {row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        
        deposito_seleccionado_info = st.sidebar.selectbox("Selecciona un depósito a eliminar", df_display_deposits["Display"])
        index_to_delete = int(deposito_seleccionado_info.split(' - ')[0]) if deposito_seleccionado_info else None

        if st.sidebar.button("🗑️ Eliminar depósito seleccionado"):
            if index_to_delete is not None and st.sidebar.checkbox("✅ Confirmar eliminación"):
                delete_deposit_record(index_to_delete)
            else:
                st.sidebar.warning("Marca la casilla para confirmar o selecciona un depósito.")
    else:
        st.sidebar.info("No hay depósitos para eliminar.")

def render_edit_deposit_section():
    """Sección para editar depósitos."""
    st.sidebar.subheader("✏️ Editar Depósito")
    if not st.session_state.df.empty:
        df_display_deposits = st.session_state.df.copy()
        df_display_deposits["Display"] = df_display_deposits.apply(
            lambda row: f"{row.name} - {row['Fecha']} - {row['Empresa']} - ${row['Monto']:.2f}", axis=1
        )
        
        deposito_seleccionado_info = st.sidebar.selectbox("Selecciona un depósito para editar", df_display_deposits["Display"])
        index_to_edit = int(deposito_seleccionado_info.split(' - ')[0]) if deposito_seleccionado_info else None

        if index_to_edit is not None and index_to_edit in st.session_state.df.index:
            deposit_to_edit = st.session_state.df.loc[index_to_edit].to_dict()
            with st.sidebar.form(f"edit_deposit_form_{index_to_edit}"):
                edited_fecha = st.date_input("Fecha", value=deposit_to_edit["Fecha"])
                edited_empresa = st.selectbox("Empresa", PROVEEDORES, index=PROVEEDORES.index(deposit_to_edit["Empresa"]))
                edited_agencia = st.selectbox("Agencia", AGENCIAS, index=AGENCIAS.index(deposit_to_edit["Agencia"]))
                edited_monto = st.number_input("Monto ($)", value=float(deposit_to_edit["Monto"]), min_value=0.0, format="%.2f")
                submit_edit_deposit = st.form_submit_button("💾 Guardar Cambios")

                if submit_edit_deposit and edited_monto > 0:
                    updated_data = {
                        "Fecha": edited_fecha,
                        "Empresa": edited_empresa,
                        "Agencia": edited_agencia,
                        "Monto": edited_monto
                    }
                    edit_deposit_record(index_to_edit, updated_data)
                elif submit_edit_deposit:
                    st.error("El monto debe ser mayor que cero.")
    else:
        st.sidebar.info("No hay depósitos para editar.")

def render_import_excel_section():
    """Sección para importar datos desde Excel."""
    st.subheader("📁 Importar datos desde Excel")
    st.info("Asegúrate de que tu archivo Excel tenga las siguientes hojas y columnas:")
    st.markdown("- **Hoja 1 (registro de proveedores):** `Fecha`, `Proveedor`, `Cantidad`, `Peso Salida (kg)`, `Peso Entrada (kg)`, `Tipo Documento`, `Cantidad de gavetas`, `Precio Unitario ($)`")
    st.markdown("- **Hoja 2 (registro de depositos):** `Fecha`, `Empresa`, `Agencia`, `Monto`")
    st.markdown("- **Hoja 3 (registro de notas de debito):** `Fecha`, `Descuento`, `Descuento real`")
    
    archivo_excel = st.file_uploader("Sube tu archivo Excel (.xlsx)", type=["xlsx"])
    if archivo_excel is not None:
        import_excel_data(archivo_excel)

def render_supplier_registration_form():
    """Formulario de registro de proveedores."""
    st.subheader("➕ Registro de Proveedores")
    with st.form("formulario_registro_proveedor", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha = st.date_input("Fecha", value=datetime.today().date())
            proveedor = st.selectbox("Proveedor", PROVEEDORES)
        with col2:
            cantidad = st.number_input("Cantidad", min_value=0, step=1)
            peso_salida = st.number_input("Peso Salida (kg)", min_value=0.0, step=0.1, format="%.2f")
        with col3:
            peso_entrada = st.number_input("Peso Entrada (kg)", min_value=0.0, step=0.1, format="%.2f")
            documento = st.selectbox("Tipo Documento", TIPOS_DOCUMENTO)
        with col4:
            gavetas = st.number_input("Cantidad de gavetas", min_value=0, step=1)
            precio_unitario = st.number_input("Precio Unitario ($)", min_value=0.0, step=0.01, format="%.2f")

        enviar = st.form_submit_button("➕ Agregar Registro")
        if enviar:
            add_supplier_record(fecha, proveedor, cantidad, peso_salida, peso_entrada, documento, gavetas, precio_unitario)

def render_debit_note_form():
    """Formulario para notas de débito."""
    st.subheader("📝 Registro de Nota de Débito")
    with st.form("nota_debito_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            fecha_nota = st.date_input("Fecha de Nota", value=datetime.today().date())
        with col2:
            descuento = st.number_input("Descuento (%)", min_value=0.0, max_value=1.0, step=0.01, format="%.2f", value=0.0)
        with col3:
            descuento_real = st.number_input("Descuento Real ($)", min_value=0.0, step=0.01, format="%.2f", value=0.0)
        
        agregar_nota = st.form_submit_button("➕ Agregar Nota de Débito")
        if agregar_nota and (descuento_real > 0 or descuento > 0):
            add_debit_note(fecha_nota, descuento, descuento_real)
        elif agregar_nota:
            st.error("Ingresa un Descuento (%) o Descuento Real ($) mayor que cero.")

def render_delete_debit_note_section():
    """Sección para eliminar notas de débito."""
    st.subheader("🗑️ Eliminar Nota de Débito")
    if not st.session_state.notas.empty:
        df_display_notes = st.session_state.notas.copy()
        df_display_notes["Display"] = df_display_notes.apply(
            lambda row: f"{row.name} - {row['Fecha']} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        
        nota_seleccionada_info = st.selectbox("Selecciona una nota de débito para eliminar", df_display_notes["Display"])
        index_to_delete = int(nota_seleccionada_info.split(' - ')[0]) if nota_seleccionada_info else None
        
        if st.button("🗑️ Eliminar Nota de Débito seleccionada"):
            if index_to_delete is not None and st.checkbox("✅ Confirmar eliminación"):
                delete_debit_note_record(index_to_delete)
            else:
                st.warning("Marca la casilla para confirmar o selecciona una nota.")
    else:
        st.info("No hay notas de débito para eliminar.")

def render_edit_debit_note_section():
    """Sección para editar notas de débito."""
    st.subheader("✏️ Editar Nota de Débito")
    if not st.session_state.notas.empty:
        df_display_notes = st.session_state.notas.copy()
        df_display_notes["Display"] = df_display_notes.apply(
            lambda row: f"{row.name} - {row['Fecha']} - Descuento real: ${row['Descuento real']:.2f}", axis=1
        )
        
        nota_seleccionada_info = st.selectbox("Selecciona una nota de débito para editar", df_display_notes["Display"])
        index_to_edit = int(nota_seleccionada_info.split(' - ')[0]) if nota_seleccionada_info else None

        if index_to_edit is not None and index_to_edit in st.session_state.notas.index:
            note_to_edit = st.session_state.notas.loc[index_to_edit].to_dict()
            with st.form(f"edit_debit_note_form_{index_to_edit}"):
                edited_fecha_nota = st.date_input("Fecha de Nota", value=note_to_edit["Fecha"])
                edited_descuento = st.number_input("Descuento (%)", value=float(note_to_edit["Descuento"]), min_value=0.0, max_value=1.0, step=0.01, format="%.2f")
                edited_descuento_real = st.number_input("Descuento Real ($)", value=float(note_to_edit["Descuento real"]), min_value=0.0, step=0.01, format="%.2f")
                
                submit_edit_note = st.form_submit_button("💾 Guardar Cambios")
                if submit_edit_note and (edited_descuento > 0 or edited_descuento_real > 0):
                    updated_data = {
                        "Fecha": edited_fecha_nota,
                        "Descuento": edited_descuento,
                        "Descuento real": edited_descuento_real
                    }
                    edit_debit_note_record(index_to_edit, updated_data)
                elif submit_edit_note:
                    st.error("Ingresa un Descuento (%) o Descuento Real ($) mayor que cero.")
    else:
        st.info("No hay notas de débito para editar.")

def display_formatted_dataframe(df_source, title, columns_to_format=None, key_suffix="", editable_cols=None):
    """Muestra un DataFrame con formato de moneda y edición."""
    st.subheader(title)
    df_display = df_source.copy()

    if columns_to_format:
        for col in columns_to_format:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
                df_display[col] = df_display[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    
    if "Fecha" in df_display.columns:
        df_display["Fecha"] = df_display["Fecha"].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else "")

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
            
    edited_df = st.dataframe(
        df_display, 
        use_container_width=True, 
        hide_index=False,
        column_config=column_config,
        key=f"editable_df_{key_suffix}"
    )

    if f"editable_df_{key_suffix}" in st.session_state and st.session_state[f"editable_df_{key_suffix}"]["edited_rows"]:
        st.info("Se han detectado cambios. Presiona 'Guardar Cambios'.")
        if st.button(f"💾 Guardar Cambios en {title}"):
            df_updated_rows = st.session_state[f"editable_df_{key_suffix}"]["edited_rows"]
            original_df_to_update = df_source.copy()

            for idx_str, changes in df_updated_rows.items():
                idx = int(idx_str)
                if title == "Tabla de Registros" and original_df_to_update.loc[idx, "Proveedor"] == "BALANCE_INICIAL":
                    st.warning(f"No se pueden editar las propiedades de BALANCE_INICIAL (ID: {idx}).")
                    continue

                for col, value in changes.items():
                    original_type = df_source[col].dtype
                    if pd.api.types.is_datetime64_any_dtype(original_type) or isinstance(df_source.loc[idx, col], date):
                        try:
                            original_df_to_update.loc[idx, col] = pd.to_datetime(value).date()
                        except:
                            st.warning(f"Formato de fecha inválido en {col}, fila {idx}.")
                            original_df_to_update.loc[idx, col] = df_source.loc[idx, col]
                    elif pd.api.types.is_numeric_dtype(original_type):
                        try:
                            if editable_cols and editable_cols.get(col) == "number_int":
                                original_df_to_update.loc[idx, col] = int(value)
                            else:
                                original_df_to_update.loc[idx, col] = float(value)
                        except:
                            st.warning(f"Valor numérico inválido en {col}, fila {idx}.")
                            original_df_to_update.loc[idx, col] = df_source.loc[idx, col]
                    else:
                        original_df_to_update.loc[idx, col] = value
                
            if title == "Tabla de Registros":
                st.session_state.data = original_df_to_update
                if save_dataframe(st.session_state.data, "proveedores"):
                    st.session_state.record_edited = True
                    st.success("Cambios guardados. Recalculando saldos...")
            elif title == "Depósitos Registrados":
                st.session_state.df = original_df_to_update
                if save_dataframe(st.session_state.df, "depositos"):
                    st.session_state.deposit_edited = True
                    st.success("Cambios guardados. Recalculando saldos...")
            elif title == "Tabla de Notas de Débito":
                st.session_state.notas = original_df_to_update
                if save_dataframe(st.session_state.notas, "notas_debito"):
                    st.session_state.debit_note_edited = True
                    st.success("Cambios guardados. Recalculando saldos...")

def render_tables_and_download():
    """Renderiza las tablas y opción de descarga."""
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
        df_display_data_for_del = st.session_state.data[st.session_state.data["Proveedor"] != "BALANCE_INICIAL"].copy()
        
        if not df_display_data_for_del.empty:
            df_display_data_for_del["Display"] = df_display_data_for_del.apply(
                lambda row: f"{row.name} - {row['Fecha']} - {row['Proveedor']} - ${row['Total ($)']:.2f}" if pd.notna(row["Total ($)"]) else f"{row.name} - {row['Fecha']} - {row['Proveedor']} - Sin total",
                axis=1
            )
            registro_seleccionado_info = st.selectbox("Selecciona un registro para eliminar", df_display_data_for_del["Display"])
            index_to_delete_record = int(registro_seleccionado_info.split(' - ')[0]) if registro_seleccionado_info else None

            if st.button("🗑️ Eliminar Registro Seleccionado"):
                if index_to_delete_record is not None and st.checkbox("✅ Confirmar eliminación"):
                    delete_record(index_to_delete_record)
                else:
                    st.warning("Marca la casilla para confirmar o selecciona un registro.")
    else:
        st.subheader("Tabla de Registros")
        st.info("No hay registros. Agrega algunos o importa desde Excel.")

    st.markdown("---")
    editable_cols_notes = {
        "Fecha": "date",
        "Descuento": "number",
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
        render_edit_debit_note_section()
    else:
        st.subheader("Tabla de Notas de Débito")
        st.info("No hay notas de débito registradas.")

    st.markdown("---")
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
        else:
            st.info("No hay depósitos registrados.")

    st.markdown("---")
    @st.cache_data
    def convertir_excel(df_data, df_deposits, df_notes):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_data_export = df_data[df_data["Proveedor"] != "BALANCE_INICIAL"].copy()
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
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

def get_image_as_base64(fig):
    """Convierte una figura de Matplotlib a base64."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return img_base64

def generate_pdf_report(title, content_elements, filename="reporte.pdf"):
    """Genera un PDF con el contenido dado."""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{title}</b>", styles['h1']))
    story.append(Spacer(1, 0.2 * inch))

    for element in content_elements:
        story.append(element)
        story.append(Spacer(1, 0.1 * inch))

    try:
        doc.build(story)
        with open(filename, "rb") as f:
            pdf_bytes = f.read()
        st.download_button(
            label=f"🖨️ Imprimir {title} (PDF)",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Error al generar el PDF: {e}")

def create_table_for_pdf(df, title, columns_to_format=None):
    """Crea una tabla para ReportLab."""
    if df.empty:
        return Paragraph(f"No hay datos para '{title}'.", getSampleStyleSheet()['Normal'])

    df_pdf = df.copy()
    if "Display" in df_pdf.columns:
        df_pdf = df_pdf.drop(columns=["Display"])

    if columns_to_format:
        for col in columns_to_format:
            if col in df_pdf.columns:
                df_pdf[col] = pd.to_numeric(df_pdf[col], errors='coerce')
                df_pdf[col] = df_pdf[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    
    data = [df_pdf.columns.tolist()] + df_pdf.values.astype(str).tolist()
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#004d40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    return table

def render_weekly_report():
    """Reporte semanal."""
    st.header("📈 Reporte Semanal")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    content_elements = []

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)
        if not df.empty:
            df["YearWeek"] = df["Fecha"].dt.strftime('%Y-%U')
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
            st.info("No hay datos con fecha válida.")
            content_elements.append(Paragraph("No hay datos con fecha válida.", getSampleStyleSheet()['Normal']))
    else:
        st.info("No hay datos para el reporte semanal.")
        content_elements.append(Paragraph("No hay datos para el reporte semanal.", getSampleStyleSheet()['Normal']))

    if st.button("🖨️ Imprimir Reporte Semanal"):
        generate_pdf_report("Reporte Semanal de Proveedores", content_elements, "reporte_semanal.pdf")

def render_monthly_report():
    """Reporte mensual."""
    st.header("📊 Reporte Mensual")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    content_elements = []

    if not df.empty:
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df.dropna(subset=["Fecha"], inplace=True)
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
        st.info("No hay datos para el reporte mensual.")
        content_elements.append(Paragraph("No hay datos para el reporte mensual.", getSampleStyleSheet()['Normal']))
    
    if st.button("🖨️ Imprimir Reporte Mensual"):
        generate_pdf_report("Reporte Mensual de Proveedores", content_elements, "reporte_mensual.pdf")

def render_charts():
    """Gráficos de datos."""
    st.header("📊 Gráficos de Proveedores y Saldo")
    df = st.session_state.data.copy()
    df = df[df["Proveedor"] != "BALANCE_INICIAL"].copy()
    content_elements = []

    if df.empty:
        st.info("No hay datos suficientes para generar gráficos.")
        return

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df.dropna(subset=["Fecha"], inplace=True)

    st.subheader("Total por Proveedor")
    df["Total ($)"] = pd.to_numeric(df["Total ($)"], errors='coerce').fillna(0)
    total_por_proveedor = df.groupby("Proveedor")["Total ($)"].sum().sort_values(ascending=False)
    
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
        st.info("No hay datos de 'Total ($)' por proveedor.")
        content_elements.append(Paragraph("No hay datos de 'Total ($)' por proveedor.", getSampleStyleSheet()['Normal']))
    
    st.subheader("Evolución del Saldo Acumulado")
    df_ordenado = df.sort_values("Fecha")
    df_ordenado["Saldo Acumulado"] = pd.to_numeric(df_ordenado["Saldo Acumulado"], errors='coerce').fillna(INITIAL_ACCUMULATED_BALANCE)
    df_ordenado = df_ordenado[df_ordenado['Fecha'].notna()]
    
    if not df_ordenado.empty:
        daily_last_saldo = df_ordenado.groupby("Fecha")["Saldo Acumulado"].last().reset_index()
        fig_saldo, ax2 = plt.subplots(figsize=(12, 6))
        ax2.plot(daily_last_saldo["Fecha"], daily_last_saldo["Saldo Acumulado"], marker="o", linestyle='-', color='green')
        ax2.set_ylabel("Saldo Acumulado ($)")
        ax2.set_title("Evolución del Saldo Acumulado")
        ax2.grid(True, linestyle='--', alpha=0.7)
        ax2.ticklabel_format(style='plain', axis='y')
        plt.xticks(rotation=45, ha='right')
        formatter = mticker.FormatStrFormatter('$%.2f')
        ax2.yaxis.set_major_formatter(formatter)
        plt.tight_layout()
        st.pyplot(fig_saldo)
        content_elements.append(Paragraph("<b>Evolución del Saldo Acumulado</b>", getSampleStyleSheet()['h2']))
        content_elements.append(RImage(BytesIO(base64.b64decode(get_image_as_base64(fig_saldo))), width=6*inch, height=3*inch))
    else:
        st.info("No hay datos de 'Saldo Acumulado'.")
        content_elements.append(Paragraph("No hay datos de 'Saldo Acumulado'.", getSampleStyleSheet()['Normal']))

    if st.button("🖨️ Imprimir Gráficos (PDF)"):
        generate_pdf_report("Gráficos de Proveedores y Saldo", content_elements, "graficos_proveedores.pdf")

# --- CONFIGURACIÓN PRINCIPAL ---
st.title("Sistema de Gestión de Proveedores - Producto Pollo")
initialize_session_state()

st.sidebar.title("Menú Principal")
opcion = st.sidebar.selectbox("Selecciona una vista", ["Registro", "Reporte Semanal", "Reporte Mensual", "Gráficos"])

if opcion == "Registro":
    st.sidebar.markdown("---")
    render_deposit_registration_form()
    render_delete_deposit_section()
    render_edit_deposit_section()
    st.sidebar.markdown("---")
    render_import_excel_section()
    st.markdown("---")
    render_supplier_registration_form()
    st.markdown("---")
    render_debit_note_form()
    st.markdown("---")
    render_tables_and_download()
elif opcion == "Reporte Semanal":
    render_weekly_report()
elif opcion == "Reporte Mensual":
    render_monthly_report()
elif opcion == "Gráficos":
    render_charts()

if any(st.session_state[flag] for flag in ["deposit_added", "deposit_deleted", "record_added", "record_deleted", 
                                           "data_imported", "debit_note_added", "debit_note_deleted", 
                                           "record_edited", "deposit_edited", "debit_note_edited"]):
    for flag in ["deposit_added", "deposit_deleted", "record_added", "record_deleted", 
                 "data_imported", "debit_note_added", "debit_note_deleted", 
                 "record_edited", "deposit_edited", "debit_note_edited"]:
        st.session_state[flag] = False
    recalculate_accumulated_balances()
    st.rerun()
