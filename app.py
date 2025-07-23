import streamlit as st
import requests
import os
import time
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth
from google.cloud import firestore
import uuid
import json
import streamlit_authenticator
import yaml
from yaml.loader import SafeLoader

# ========== SETTINGS ==========
OAUTH_PROVIDER = "google"  # "google" or "microsoft"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
REDIRECT_URI = "http://localhost:8501"  # Update for deployment!
CONFIG_PATH = "config.yaml"

# ========== CHAT FUNCTIONS (unchanged) ==========

def save_chat(user_id, chat_id, chat_title, messages):
    if not chat_title and messages:
        chat_title = messages[0]["text"][:30]
    chat_ref = db.collection('users').document(user_id).collection('chats').document(chat_id)
    chat_ref.set({
        'created_at': firestore.SERVER_TIMESTAMP,
        'title': chat_title,
        'messages': messages
    })

def list_user_chats(user_id):
    chats_ref = db.collection('users').document(user_id).collection('chats')
    chats = chats_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()
    chat_list = []
    for c in chats:
        data = c.to_dict()
        chat_list.append({
            'id': c.id,
            'title': data.get('title', 'Untitled'),
            'created_at': data.get('created_at'),
            'messages': data.get('messages', [])
        })
    return chat_list

def get_gemini_title(messages):
    chat_content = "\n".join([f"{m['role']}: {m['text']}" for m in messages[:2]])
    prompt = (
        "Summarize this conversation so far with a short, descriptive title (max 8 words):\n"
        + chat_content
    )
    return get_gemini_response(prompt).strip().replace('"','')

def get_gemini_response(prompt):
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(GEMINI_API_URL, headers=headers, json=data)
    if response.ok:
        res_json = response.json()
        try:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        except Exception:
            return "No response from Gemini."
    else:
        return f"Error: {response.text}"

def verify_firebase_token(token):
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token  # Contains uid, email, etc.
    except Exception as e:
        st.error(f"Token verification error: {e}")
        return None

def delete_chat(user_id, chat_id):
    db.collection('users').document(user_id).collection('chats').document(chat_id).delete()

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as file:
            config = yaml.load(file, Loader=SafeLoader)
    else:
        config = {
            'credentials': {'usernames': {}},
            'cookie': {'expiry_days': 3, 'key': 'cookie_key', 'name': 'chatbot_cookie'},
            'preauthorized': {'emails': []}
        }
    return config

def save_config(config):
    with open(CONFIG_PATH, 'w') as file:
        yaml.dump(config, file)

# ========== PARSE TOKEN FROM URL ==========
query_params = st.query_params
id_token = None
if "token" in query_params:
    token_value = query_params["token"]
    if isinstance(token_value, list) and len(token_value) > 0:
        id_token = token_value[0]
    elif isinstance(token_value, str):
        id_token = token_value
    if id_token:
        st.session_state.mode = "login"

# ========== SECRETS / ENV ==========
GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
MS_CLIENT_ID = st.secrets["MS_CLIENT_ID"]
MS_CLIENT_SECRET = st.secrets["MS_CLIENT_SECRET"]

# ========== MODE SELECTION ==========
if "mode" not in st.session_state:
    st.session_state.mode = None

if st.session_state.mode is None:
    st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
    st.title("🤖 Welcome to Gemini Chatbot")
    st.markdown("Choose a mode to continue:")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔒 Sign in with Google/Microsoft"):
            st.session_state.mode = "login"
            st.rerun()
    with col2:
        if st.button("🚀 Continue as Guest"):
            st.session_state.mode = "guest"
            st.rerun()
    st.stop()

# ========== Gemini API ==========
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"

# ========== GUEST MODE ==========
if st.session_state.mode == "guest":
    st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
    st.title("🤖 Gemini Chatbot (Guest Mode)")
    st.caption("Chat as a guest (your conversation will NOT be saved)")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    with st.form(key="chat_form_guest", clear_on_submit=True):
        user_input = st.text_input("Type your message...", key="input_field_guest")
        submitted = st.form_submit_button("Send")

    # Chat bubbles display (unchanged) ...
    for chat in st.session_state.chat_history:
        if chat["role"] == "user":
            st.markdown(
                f"""
                <div style="display: flex; justify-content: flex-end; align-items: flex-end; margin: 12px 0;">
                    <div style="background: #0078fe; color: white; padding: 12px 18px; border-radius: 16px 16px 2px 16px; margin-left: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                        {chat['text']}
                    </div>
                    <div style="margin-left: 6px; font-size: 1.6em;">🧑</div>
                </div>
                """,
                unsafe_allow_html=True)
        else:
            st.markdown(
                f"""
                <div style="display: flex; justify-content: flex-start; align-items: flex-end; margin: 12px 0;">
                    <div style="margin-right: 6px; font-size: 1.6em;">🤖</div>
                    <div style="background: #f1f0f0; color: #222; padding: 12px 18px; border-radius: 16px 16px 16px 2px; margin-right: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                        {chat['text']}
                """,
                unsafe_allow_html=True)

    if submitted and user_input:
        # (typing animation unchanged)
        user_placeholder = st.empty()
        partial_user_text = ""
        for char in user_input:
            partial_user_text += char
            user_placeholder.markdown(
                f"""
                <div style='display:flex; justify-content:flex-end; align-items:flex-end; margin:10px 0;'>
                    <div style='background:#0078fe; color:white; padding:12px 18px; border-radius:16px 16px 2px 16px; max-width:60%; min-height:38px; word-break:break-word;'>
                        {partial_user_text}<span style="color:#eee;">▌</span>
                    </div>
                    <div style='margin-left:8px;font-size:1.5em;'>🧑</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            time.sleep(0.012)
        user_placeholder.markdown(
            f"""
            <div style='display:flex; justify-content:flex-end; align-items:flex-end; margin:10px 0;'>
                <div style='background:#0078fe; color:white; padding:12px 18px; border-radius:16px 16px 2px 16px; max-width:60%; min-height:38px; word-break:break-word;'>
                    {user_input}
                </div>
                <div style='margin-left:8px;font-size:1.5em;'>🧑</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.session_state.chat_history.append({"role": "user", "text": user_input})

        # Gemini response animation (unchanged)
        bot_placeholder = st.empty()
        with st.spinner("Gemini is thinking..."):
            bot_response = get_gemini_response(user_input)
            partial_bot_text = ""
            for char in bot_response:
                partial_bot_text += char
                bot_placeholder.markdown(
                    f"""
                    <div style='display:flex; justify-content:flex-start; align-items:flex-end; margin:10px 0;'>
                        <div style='margin-right:8px;font-size:1.5em;'>🤖</div>
                        <div style='background:#f1f0f0; color:#222; padding:12px 18px; border-radius:16px 16px 16px 2px; max-width:60%; min-height:38px; word-break:break-word;'>
                            {partial_bot_text}<span style="color:#888;">▌</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                time.sleep(0.012)
            bot_placeholder.markdown(
                f"""
                <div style='display:flex; justify-content:flex-start; align-items:flex-end; margin:10px 0;'>
                    <div style='margin-right:8px;font-size:1.5em;'>🤖</div>
                    <div style='background:#f1f0f0; color:#222; padding:12px 18px; border-radius:16px 16px 16px 2px; max-width:60%; min-height:38px; word-break:break-word;'>
                        {bot_response}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.session_state.chat_history.append({"role": "gemini", "text": bot_response})
        st.rerun()

    if st.button("⬅️ Back to Home"):
        st.session_state.mode = None
        st.session_state.chat_history = []
        st.rerun()
    st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)
    st.stop()

# ========== LOGIN/AUTH/FIRESTORE MODE ==========

if st.session_state.mode == "login":

    config = load_config()

    menu = st.radio("Choose action", ["Login", "Sign Up"])

    if menu == "Sign Up":
        st.header("Create a New Account")
        new_username = st.text_input("Choose a username")
        new_password = st.text_input("Choose a password", type="password")
        new_email = st.text_input("Your email (optional)")

        if st.button("Sign Up"):
            if not new_username or not new_password:
                st.warning("Username and password required!")
            elif new_username in config['credentials']['usernames']:
                st.error("Username already exists!")
            else:
                hashed_pw = streamlit_authenticator.Hasher([new_password]).generate()
                config['credentials']['usernames'][new_username] = {
                    'email': new_email,
                    'name': new_username,
                    'password': hashed_pw
                }
                save_config(config)
                st.success("Account created! You can now log in.")
                st.balloons()

    if menu == "Login":
        authenticator = streamlit_authenticator.Authenticate(
            config['credentials'],
            config['cookie']['name'],
            config['cookie']['key'],
            config['cookie']['expiry_days'],
        )

        login_result = authenticator.login('main', 'main')
        if login_result is not None:
            name, authentication_status, username = login_result
            if authentication_status:
                st.success(f"Logged in as {name}!")
                user_id = username or name
                # ========== FIRESTORE INIT ==========
            if not hasattr(st, 'firestore_db'):
                service_account_info = json.loads(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
                st.firestore_db = firestore.Client.from_service_account_info(service_account_info)
            db = st.firestore_db

            # ---- SIDEBAR: Past Chats, New Chat, Logout ----
            if "chat_id" not in st.session_state:
                st.session_state.chat_id = None
            if "chat_history" not in st.session_state:
                st.session_state.chat_history = []
            if "chat_title" not in st.session_state:
                st.session_state.chat_title = ""

            if st.sidebar.button("🚪 Logout"):
                for key in ["chat_id", "chat_history", "chat_title", "mode"]:
                    if key in st.session_state:
                        del st.session_state[key]
                st.experimental_rerun()

            st.sidebar.header("Past Chats")
            if st.sidebar.button("➕ New Chat"):
                st.session_state.chat_history = []
                st.session_state.chat_id = str(uuid.uuid4())
                st.session_state.chat_title = ""
                st.rerun()

            chat_summaries = list_user_chats(user_id)
            for chat in chat_summaries:
                chat_col, del_col = st.sidebar.columns([6, 1])
                with chat_col:
                    if st.button(chat['title'], key=chat['id']):
                        st.session_state.chat_id = chat['id']
                        st.session_state.chat_history = chat['messages']
                        st.session_state.chat_title = chat['title']
                        st.rerun()
                with del_col:
                    if st.button("🗑️", key="del_" + chat['id']):
                        delete_chat(user_id, chat['id'])
                        if st.session_state.get("chat_id") == chat['id']:
                            st.session_state.chat_id = None
                            st.session_state.chat_history = []
                            st.session_state.chat_title = ""
                        st.rerun()

            st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
            st.title("🤖 Gemini Chatbot")

            if st.button("🗑️ Clear Conversation", type="primary"):
                st.session_state.chat_history = []

            with st.form(key="chat_form", clear_on_submit=True):
                user_input = st.text_input("Type your message...", key="input_field")
                submitted = st.form_submit_button("Send")

            for chat in st.session_state.chat_history:
                if chat["role"] == "user":
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: flex-end; align-items: flex-end; margin: 12px 0;">
                            <div style="background: #0078fe; color: white; padding: 12px 18px; border-radius: 16px 16px 2px 16px; margin-left: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                                {chat['text']}
                            </div>
                            <div style="margin-left: 6px; font-size: 1.6em;">🧑</div>
                        </div>
                        """,
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: flex-start; align-items: flex-end; margin: 12px 0;">
                            <div style="margin-right: 6px; font-size: 1.6em;">🤖</div>
                            <div style="background: #f1f0f0; color: #222; padding: 12px 18px; border-radius: 16px 16px 16px 2px; margin-right: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                                {chat['text']}
                        """,
                        unsafe_allow_html=True)

            if submitted and user_input:
                user_placeholder = st.empty()
                partial_user_text = ""
                for char in user_input:
                    partial_user_text += char
                    user_placeholder.markdown(
                        f"""
                        <div style='display:flex; justify-content:flex-end; align-items:flex-end; margin:10px 0;'>
                            <div style='background:#0078fe; color:white; padding:12px 18px; border-radius:16px 16px 2px 16px; max-width:60%; min-height:38px; word-break:break-word;'>
                                {partial_user_text}<span style="color:#eee;">▌</span>
                            </div>
                            <div style='margin-left:8px;font-size:1.5em;'>🧑</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    time.sleep(0.012)
                user_placeholder.markdown(
                    f"""
                    <div style='display:flex; justify-content:flex-end; align-items:flex-end; margin:10px 0;'>
                        <div style='background:#0078fe; color:white; padding:12px 18px; border-radius:16px 16px 2px 16px; max-width:60%; min-height:38px; word-break:break-word;'>
                            {user_input}
                        </div>
                        <div style='margin-left:8px;font-size:1.5em;'>🧑</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                st.session_state.chat_history.append({"role": "user", "text": user_input})

                bot_placeholder = st.empty()
                with st.spinner("Gemini is thinking..."):
                    bot_response = get_gemini_response(user_input)
                    partial_bot_text = ""
                    for char in bot_response:
                        partial_bot_text += char
                        bot_placeholder.markdown(
                            f"""
                            <div style='display:flex; justify-content:flex-start; align-items:flex-end; margin:10px 0;'>
                                <div style='margin-right:8px;font-size:1.5em;'>🤖</div>
                                <div style='background:#f1f0f0; color:#222; padding:12px 18px; border-radius:16px 16px 16px 2px; max-width:60%; min-height:38px; word-break:break-word;'>
                                    {partial_bot_text}<span style="color:#888;">▌</span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        time.sleep(0.012)
                    bot_placeholder.markdown(
                        f"""
                        <div style='display:flex; justify-content:flex-start; align-items:flex-end; margin:10px 0;'>
                            <div style='margin-right:8px;font-size:1.5em;'>🤖</div>
                            <div style='background:#f1f0f0; color:#222; padding:12px 18px; border-radius:16px 16px 16px 2px; max-width:60%; min-height:38px; word-break:break-word;'>
                                {bot_response}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                st.session_state.chat_history.append({"role": "gemini", "text": bot_response})

                if not st.session_state.get("chat_id"):
                    st.session_state.chat_id = str(uuid.uuid4())
                chat_id = st.session_state.chat_id

                if (not st.session_state.get("chat_title") or st.session_state["chat_title"] == "Conversation with Gemini") and len(st.session_state.chat_history) >= 2:
                    gemini_title = get_gemini_title(st.session_state.chat_history[:2])
                    st.session_state["chat_title"] = gemini_title
                else:
                    gemini_title = st.session_state.get("chat_title", "")

                save_chat(user_id, chat_id, gemini_title, st.session_state.chat_history)
                st.rerun()
        else:
            st.warning("Please log in.")

        st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)
        st.stop()

st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)