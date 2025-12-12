import pandas as pd
import numpy as np

def clean_dataframe(df):
    """Limpia valores infinitos y nulos básicos"""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None)

def apply_global_filters(df, filters):
    if not filters: return df
    df_filtered = df.copy()
    for col, val in filters.items():
        if col in df_filtered.columns:
            df_filtered = df_filtered[df_filtered[col].astype(str) == str(val)]
    return df_filtered

def process_component_data(df, component):
    try:
        c_type = component.get('type')
        config = component.get('config', {})
        chart_type = component.get('chart_type') # Necesario para la lógica de Pie
        
        # --- 1. PROCESAR KPI ---
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            
            val = 0
            if op == 'count':
                val = len(df)
            elif col and col in df.columns:
                numeric_series = pd.to_numeric(df[col], errors='coerce').fillna(0)
                if op == 'sum': val = numeric_series.sum()
                elif op == 'mean': val = numeric_series.mean()
                elif op == 'max': val = numeric_series.max()
                elif op == 'min': val = numeric_series.min()
            
            return {"value": val, "label": component.get('title')}

        # --- 2. PROCESAR MAPA ---
        elif c_type == 'map':
            lat = config.get('lat')
            lon = config.get('lon')
            label = config.get('label')
            
            if lat in df.columns and lon in df.columns:
                cols = [lat, lon]
                if label and label in df.columns: cols.append(label)
                # Convertimos a numérico para evitar errores en el front
                df[lat] = pd.to_numeric(df[lat], errors='coerce')
                df[lon] = pd.to_numeric(df[lon], errors='coerce')
                return df[cols].dropna().head(1000).to_dict(orient='records')
            return []

        # --- 3. PROCESAR GRÁFICO ---
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20) # Límite por defecto para barras
            
            if not x or x not in df.columns: return []

            # A. Agrupación y Cálculo
            if op == 'count':
                df_res = df[x].value_counts().reset_index()
                df_res.columns = [x, 'value']
            
            elif y and y in df.columns:
                df[y] = pd.to_numeric(df[y], errors='coerce').fillna(0)
                if op == 'sum': df_res = df.groupby(x)[y].sum().reset_index()
                elif op == 'mean': df_res = df.groupby(x)[y].mean().reset_index()
                else: df_res = df.groupby(x)[y].sum().reset_index()
                df_res.columns = [x, 'value']
            else:
                return []

            # B. Ordenar
            df_res = df_res.sort_values(by='value', ascending=False)

            # C. LÓGICA ESPECIAL PARA PIE CHARTS (Top 9 + Otros)
            if chart_type == 'pie' and len(df_res) > 10:
                top_9 = df_res.iloc[:9]
                others_val = df_res.iloc[9:]['value'].sum()
                
                # Crear fila "Otros"
                others_row = pd.DataFrame({x: ['Otros'], 'value': [others_val]})
                df_res = pd.concat([top_9, others_row])
            else:
                # Para barras y otros, respetamos el límite numérico simple
                df_res = df_res.head(limit)
            
            return {
                "dimensions": [x, 'value'],
                "source": df_res.to_dict(orient='records')
            }
            
        return None
    except Exception as e:
        print(f"Error procesando componente {component.get('id')}: {e}")
        return None