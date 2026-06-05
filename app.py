import streamlit as st
import pandas as pd
import requests
from io import StringIO

st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid=0"

MAPA_N_NATURAL = {
    "UPS - 1": 5,
    "UPS - 2": 3,
    "UPS - 3": 3,
    "UPS - 4": 3,
    "UPS - 6": 4,
    "UPS - 7": 4,
    "UPS - 8": 4,
    "ACS - 01": 3,
}

@st.cache_data(ttl=2)
def carregar_base():
    try:
        response = requests.get(URL_BASE, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        m_row, m_col = -1, -1
        for r in range(min(50, len(df_raw))):
            for c in range(len(df_raw.columns)):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    if str(df_raw.iloc[r + 2, c]).lower() != "nan":
                        m_row, m_col = r, c
                        break
            if m_row != -1:
                break
        if m_row == -1:
            return pd.DataFrame()
        dados = df_raw.iloc[m_row + 1:].copy()
        lista_final = []
        cel_atual = "Indefinida"
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            try:
                unid = pd.to_numeric(dados.iloc[i, m_col + 1].replace(",", "."), errors="coerce")
                desc = str(dados.iloc[i, m_col + 2]).strip()
                ups_linha = str(dados.iloc[i, m_col + 3]).strip().upper()
                if any(x in ups_linha for x in ["UPS", "ACS", "ACE"]):
                    cel_atual = str(dados.iloc[i, m_col + 3]).strip()
                if mod != "nan" and len(mod) > 5 and not pd.isna(unid):
                    lista_final.append({
                        "ID": mod,
                        "UNIDADE_HORA": unid,
                        "DESCRICAO": desc,
                        "CEL_ORIGEM": cel_atual,
                        "DISPLAY": f"[{cel_atual}] {mod} - {desc} ({unid} pç/h)",
                    })
            except:
                continue
        return pd.DataFrame(lista_final)
    except:
        return pd.DataFrame()


def calcular(df_in, df_ba, h_ini, n_dia, tem_gin, sel_ups, df_paradas):
    # Tratamento inteligente para ler horários digitados como "8", "08", "8:00" ou "08:00"
    def para_min(s):
        try:
            s_str = str(s).strip().replace(",", ".")
            if not s_str or s_str.lower() == "nan":
                return -1
            if ":" in s_str:
                h, m = map(int, s_str.split(":"))
                return h * 60 + m
            else:
                # Se o usuário digitou apenas um número inteiro (ex: 8 ou 9)
                val = int(float(s_str))
                return val * 60
        except:
            return -1

    m_alm_i  = para_min("11:30")
    m_alm_f  = para_min("12:30")
    m_cafe_m = para_min("09:20")
    m_cafe_t = para_min("15:20")
    m_gin_i  = para_min("09:30")
    m_gin_f  = para_min("09:40")
    m_ini    = para_min(h_ini)

    paradas_customizadas = []
    if df_paradas is not None and not df_paradas.empty:
        for _, row in df_paradas.iterrows():
            if pd.isna(row["Início"]) or pd.isna(row["Fim"]):
                continue
            ini_p = para_min(row["Início"])
            fim_p = para_min(row["Fim"])
            motivo = str(row["Motivo"]).strip() if not pd.isna(row["Motivo"]) and str(row["Motivo"]).strip() != "" and str(row["Motivo"]).strip().lower() != "nan" else "PARADA"
            if ini_p != -1 and fim_p != -1 and fim_p > ini_p:
                paradas_customizadas.append({"ini": ini_p, "fim": fim_p, "motivo": motivo})

    marcos = ["08:30","09:30","10:30","11:30","12:30","13:30","14:30","15:30","16:30","17:30"]
    pontos = [h_ini] + [m for m in marcos if para_min(m) > m_ini]

    df_in = df_in.merge(df_ba, left_on="Equipamento", right_on="DISPLAY", how="left").reset_index(drop=True)

    def cad_real(row):
        n_nom = MAPA_N_NATURAL.get(row["CEL_ORIGEM"], 5)
        return (row["UNIDADE_HORA"] / n_nom) * n_dia

    df_in["CAD_R"] = df_in.apply(cad_real, axis=1)
    df_in["T_PC"]  = 60.0 / df_in["CAD_R"]
    df_in["FALTA"] = pd.to_numeric(df_in["Qtd"]).astype(float)

    total_ped = int(df_in["FALTA"].sum())

    res   = []
    acum  = 0.0   
    idx   = 0
    tot   = 0
    ultimo_min = None

    for p in range(len(pontos) - 1):
        p1 = para_min(pontos[p])
        p2 = para_min(pontos[p + 1])

        # ---------- ALMOÇO ----------
        if p1 == m_alm_i and p2 == m_alm_f:
            res.append({
                "Horário": f"{pontos[p]} – {pontos[p+1]}",
                "Modelos": "🍱 INTERVALO DE ALMOÇO",
                "Peças": 0,
                "Acum": int(tot),
            })
            continue

        # ---------- Minutos úteis do intervalo ----------
        mins_uteis = []
        motivos_parada_do_bloco = []

        for m in range(p1, p2):
            foi_parada_custom = False
            for pc in paradas_customizadas:
                if pc["ini"] <= m < pc["fim"]:
                    foi_parada_custom = True
                    if pc["motivo"] not in motivos_parada_do_bloco:
                        motivos_parada_do_bloco.append(pc["motivo"])
                    break
            
            if foi_parada_custom:
                continue

            if not (
                (m_cafe_m <= m < m_cafe_m + 10)
                or (m_cafe_t <= m < m_cafe_t + 10)
                or (m_alm_i  <= m < m_alm_f)
                or (tem_gin and m_gin_i <= m < m_gin_f)
            ):
                mins_uteis.append(m)

        if len(mins_uteis) == 0 and motivos_parada_do_bloco:
            res.append({
                "Horário": f"{pontos[p]} – {pontos[p+1]}",
                "Modelos": f"🛑 " + " + ".join(motivos_parada_do_bloco).upper(),
                "Peças": 0,
                "Acum": int(tot),
            })
            continue

        p_h = 0
        m_n = []  

        if motivos_parada_do_bloco:
            m_n.append(f"[{' + '.join(motivos_parada_do_bloco).upper()}]")

        for m_util in mins_uteis:
            if idx >= len(df_in):
                break

            acum += 1.0  

            while idx < len(df_in):
                t_pc = df_in.loc[idx, "T_PC"]
                if (acum + 0.1) >= t_pc - 0.001:
                    acum -= t_pc
                    if acum < 0:
                        acum = 0.0
                    df_in.loc[idx, "FALTA"] -= 1
                    tot    += 1
                    p_h    += 1
                    ultimo_min = m_util

                    nome = df_in.loc[idx, "ID"]
                    if m_n and m_n[-1].startswith(nome + " ("):
                        qtd_ant   = int(m_n[-1].split("(")[1].rstrip(")"))
                        m_n[-1]   = f"{nome} ({qtd_ant + 1})"
                    elif m_n and m_n[-1].startswith("["):
                        m_n.append(f"{nome} (1)")
                    else:
                        m_n.append(f"{nome} (1)")

                    if df_in.loc[idx, "FALTA"] <= 0:
                        idx += 1
                else:
                    break  

        res.append({
            "Horário": f"{pontos[p]} – {pontos[p+1]}",
            "Modelos": " + ".join(m_n) if m_n else "-",
            "Peças":   int(p_h),
            "Acum":    int(tot),
        })

    # ---------- Horário de término ----------
    if total_ped == 0:
        termino = "Sem demanda"
    elif tot >= total_ped and ultimo_min is not None:
        h_fim = ultimo_min // 60
        m_fim = ultimo_min % 60
        termino = f"{h_fim:02d}:{m_fim:02d}"
    elif ultimo_min is not None:
        h_fim = ultimo_min // 60
        m_fim = ultimo_min % 60
        termino = f"{h_fim:02d}:{m_fim:02d} (Capacidade Máxima do Turno)"
    else:
        termino = "Não iniciado"

    tem_sobra = tot < total_ped

    return {
        "df":        pd.DataFrame(res),
        "tot":       tot,
        "total_ped": total_ped,
        "termino":   termino,
        "tem_sobra": tem_sobra,
    }


# ===================== INTERFACE =====================
base = carregar_base()

if not base.empty:
    st.sidebar.markdown("### Tecnologia de Processos")
    st.sidebar.title("🏭 NHS Produção")

    lista_ups = sorted(base["CEL_ORIGEM"].unique().tolist())
    default_index = lista_ups.index("UPS - 1") if "UPS - 1" in lista_ups else 0
    sel_ups = st.sidebar.selectbox("Célula de Trabalho", lista_ups, index=default_index)

    n_sugerido = MAPA_N_NATURAL.get(sel_ups, 5)

    liberar_modelos = st.sidebar.checkbox("🔓 Usar modelos de outras UPS?", value=False)
    tem_gin         = st.sidebar.checkbox("🤸 Haverá Ginástica Laboral?",   value=False)
    h_ini            = st.sidebar.text_input("Início da Produção", "07:45")
    n_dia            = st.sidebar.number_input(f"Pessoas na {sel_ups}", 1, 20, value=n_sugerido)

    st.sidebar.write("---")
    st.sidebar.markdown("### 🛑 Paradas Programadas")
    df_paradas_vazias = pd.DataFrame(columns=["Início", "Fim", "Motivo"])
    
    df_p_ed = st.sidebar.data_editor(
        df_paradas_vazias,
        num_rows="dynamic",
        use_container_width=True
    )

    st.header(f"📋 Planejamento: {sel_ups}")

    if liberar_modelos:
        opcoes = sorted(base["DISPLAY"].tolist())
    else:
        opcoes = sorted(base[base["CEL_ORIGEM"] == sel_ups]["DISPLAY"].tolist())

    df_ed = st.data_editor(
        pd.DataFrame(columns=["Equipamento", "Qtd"]),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes),
            "Qtd":         st.column_config.NumberColumn("Qtd", min_value=1),
        },
    )

    if st.button("🚀 Gerar Planejamento"):
        df_v = df_ed.dropna(subset=["Equipamento", "Qtd"])
        df_v = df_v[df_v["Qtd"] > 0].copy()

        df_p_validas = df_p_ed.dropna(subset=["Início", "Fim"]) if not df_p_ed.empty else None

        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, tem_gin, sel_ups, df_p_validas)
            st.divider()

            c1, c2 = st.columns(2)
            c1.metric("Total Produzido", f"{r['tot']} pçs")
            c2.metric("Horário da Última Peça", r["termino"])

            if r["tem_sobra"]:
                faltam = r["total_ped"] - r["tot"]
                st.error(f"⚠️ Atenção: Meta não atingida por falta de tempo útil. Faltaram {faltam} peça(s).")
            else:
                st.success("🎉 Excelente! Toda a programação estimada será concluída dentro do horário.")

            def style_almoco(row):
                celula_texto = str(row["Modelos"])
                if "ALMOÇO" in celula_texto:
                    return ["background-color: #fff3cd"] * len(row)
                if "🛑" in celula_texto or "-" in celula_texto and row["Peças"] == 0:
                    return ["background-color: #f8d7da; color: #721c24;font-weight: bold;"] * len(row)
                return [""] * len(row)

            st.subheader("📅 Cronograma Detalhado por Hora")
            st.dataframe(
                r["df"].style.apply(style_almoco, axis=1),
                use_container_width=True,
                height=450,
            )
else:
    st.error("⚠️ Base de dados não carregada. Verifique se a aba 'BASE' é a primeira da planilha.")
