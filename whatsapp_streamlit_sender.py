# whatsapp_streamlit_sender.py
# Streamlit UI para envio em massa via WhatsApp Cloud API (Meta)
# ATENÇÃO: Use com responsabilidade. Mantenha TOKEN/PHONE_NUMBER_ID em secrets.

import streamlit as st
import pandas as pd
import requests
import time
import threading
import random
from datetime import datetime

st.set_page_config(page_title="WSender", layout="wide")

# --- CSS tema escuro ---
st.markdown("""
<style>
body { background-color: #0b1220; color: #e6eef8; }
section.main { background-color: #071021; }
.stButton>button { background-color:#0f1724; color: #e6eef8; border:1px solid #2b394b; }
</style>
""", unsafe_allow_html=True)

st.title("WSender — Envio em Massa (WhatsApp Cloud API)")
st.caption("Use somente com números autorizados. Envio em massa pode acarretar bloqueio.")

# session state
if 'report' not in st.session_state:
    st.session_state.report = pd.DataFrame(columns=['ID','phone','status','detail'])
if 'cancel' not in st.session_state:
    st.session_state.cancel = False
if 'running' not in st.session_state:
    st.session_state.running = False

# sidebar config
with st.sidebar:
    st.header("Configurações")
    token = st.text_input("TOKEN (WHATSAPP CLOUD API)", type="password")
    phone_id = st.text_input("PHONE_NUMBER_ID")
    st.markdown("---")
    uploaded_file = st.file_uploader("Carregar CSV/XLSX (coluna: phone, opcional: nome)", type=['csv','xlsx'])
    st.markdown("---")
    st.subheader("Taxa de envio")
    mode = st.radio("Modo", ["Mensagens por hora", "Intervalo entre mensagens (segundos)"])
    if mode == "Mensagens por hora":
        per_hour = st.slider("Enviar (por hora)", 1, 250, 60)
        avg_delay = 3600.0 / max(per_hour,1)
        st.caption(f"~{int(avg_delay)} segundos em média entre mensagens")
    else:
        avg_delay = st.slider("Intervalo médio (segundos)", 1, 600, 10)
    jitter = st.slider("Jitter aleatório (s)", 0, 30, 3)
    st.markdown("---")
    cap = st.number_input("Máximo contatos nesta execução", min_value=1, max_value=10000, value=250)

# main layout
col1, col2 = st.columns([2,1])

with col1:
    st.subheader("Preview da lista")
    df = None
    if uploaded_file is not None:
        try:
            if uploaded_file.name.lower().endswith('.csv'):
                df = pd.read_csv(uploaded_file, dtype=str)
            else:
                df = pd.read_excel(uploaded_file, dtype=str)
            # detectar coluna phone
            if 'phone' not in df.columns:
                candidates = [c for c in df.columns if 'phone' in c.lower() or 'cel' in c.lower() or 'fone' in c.lower()]
                if candidates:
                    df = df.rename(columns={candidates[0]:'phone'})
                else:
                    st.error('CSV precisa da coluna "phone" (ou coluna detectável com telefone)')
            df['phone'] = df['phone'].astype(str).str.replace('[^0-9+]','', regex=True)
            st.dataframe(df.head(500))
        except Exception as e:
            st.error("Erro ao ler arquivo: " + str(e))
    else:
        st.info('Carregue CSV/XLSX com coluna "phone" (opcional "nome").')

    st.subheader("Mensagem")
    default_msg = "Olá {nome}, tudo bem? Esta é uma mensagem automática."
    message = st.text_area("Corpo (use {nome} para personalizar)", value=default_msg, height=140)

with col2:
    st.subheader("Controles")
    send_btn = st.button("Enviar")
    cancel_btn = st.button("Cancelar")
    st.markdown("---")
    st.subheader("Relatório")
    if not st.session_state.report.empty:
        csv_bytes = st.session_state.report.to_csv(index=False).encode('utf-8')
        st.download_button("Baixar relatório CSV", data=csv_bytes, file_name=f"relatorio_ws_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

if cancel_btn:
    st.session_state.cancel = True
    st.session_state.running = False
    st.warning("Cancelamento solicitado...")

# função de envio via Cloud API
def send_whatsapp_message(token, phone_id, to_number, text):
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product":"whatsapp", "to": to_number, "type":"text", "text":{"body": text}}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
    except Exception as e:
        return False, str(e), None
    if r.status_code in (200,201):
        try:
            resp = r.json()
            mid = None
            if 'messages' in resp and isinstance(resp['messages'], list) and len(resp['messages'])>0:
                mid = resp['messages'][0].get('id')
            return True, 'Enviado', mid
        except Exception:
            return True, 'Enviado (sem JSON esperado)', None
    else:
        try:
            return False, r.json(), None
        except Exception:
            return False, r.text, None

# worker para envio
def worker(df_local, token_local, phone_id_local, message_template, avg_delay_local, jitter_local, cap_local):
    st.session_state.running = True
    results = []
    total = min(len(df_local), cap_local)
    for idx in range(total):
        if st.session_state.cancel:
            break
        row = df_local.iloc[idx]
        phone = row.get('phone')
        nome = row.get('nome','') if 'nome' in df_local.columns else ''
        text = message_template.format(nome=nome) if '{nome}' in message_template else message_template
        success, detail, mid = send_whatsapp_message(token_local, phone_id_local, phone, text)
        status = 'Enviado' if success else 'Não existente'
        entry = {'ID': idx+1, 'phone': phone, 'status': status, 'detail': str(detail)}
        st.session_state.report = pd.concat([st.session_state.report, pd.DataFrame([entry])], ignore_index=True)
        # sleep with jitter
        delay = max(0, random.uniform(avg_delay_local - jitter_local, avg_delay_local + jitter_local))
        if idx < total-1:
            time.sleep(delay)
    st.session_state.running = False
    st.success("Envio finalizado (ou interrompido).")

if send_btn and not st.session_state.running:
    if uploaded_file is None:
        st.error("Carregue a lista de contatos antes de enviar.")
    elif not token or not phone_id:
        st.error("Preencha TOKEN e PHONE_NUMBER_ID na sidebar.")
    else:
        st.session_state.report = pd.DataFrame(columns=['ID','phone','status','detail'])
        st.session_state.cancel = False
        df_to_process = df.copy().reset_index(drop=True)
        thread = threading.Thread(target=worker, args=(df_to_process, token, phone_id, message, avg_delay, jitter, cap))
        thread.start()
        st.info("Envio iniciado. Acompanhe o relatório e use Cancelar para interromper.")

      
