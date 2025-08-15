import streamlit as st
import requests
import os
import time
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import auth
from google.cloud import firestore
import uuid
import json
import streamlit_authenticator
import yaml
from yaml.loader import SafeLoader
import hashlib

# ========== CHAT FUNCTIONS (unchanged) ==========

def save_chat(user_id, chat_id, chat_title, messages):
    if not chat_title and messages:
        chat_title = messages[0]["text"][:30]
    db = get_db()
    chat_ref = db.collection('users').document(user_id).collection('chats').document(chat_id)
    chat_ref.set({
        'created_at': firestore.SERVER_TIMESTAMP,
        'title': chat_title,
        'messages': messages
    })

def list_user_chats(user_id):
    db = get_db()
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
    db = get_db()
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

def signup_user(username, password, email):
    db = get_db()
    users_ref = db.collection('users')
    user_doc = users_ref.document(username)
    if user_doc.get().exists:
        st.error("Username already exists!")
    else:
        user_doc.set({
            'username': username,
            'password': hash_password(password),
            'email': email,
            'created_at': firestore.SERVER_TIMESTAMP,
        })
        st.success("Account created! You can now log in.")

def hash_password(password):
    # Simple hash with sha256; for real-world, use bcrypt or firebase's built-in auth!
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    db = get_db()
    user_doc = db.collection('users').document(username).get()
    if user_doc.exists:
        user_data = user_doc.to_dict()
        return hash_password(password) == user_data['password'], user_data
    return False, None

def get_db():
    if not hasattr(st.session_state, 'firestore_db'):
        # Only initialize if not already present
        service_account_info = json.loads(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
        st.session_state.firestore_db = firestore.Client.from_service_account_info(service_account_info)
    return st.session_state.firestore_db

# ========== SECRETS / ENV ==========
GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
MS_CLIENT_ID = st.secrets["MS_CLIENT_ID"]
MS_CLIENT_SECRET = st.secrets["MS_CLIENT_SECRET"]

CONFIG_PATH = "config.yaml"

# session flags
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "just_logged_in" not in st.session_state:
    st.session_state.just_logged_in = False

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

    # helpers (scoped to login mode)
    def get_db():
        if not hasattr(st.session_state, "firestore_db"):
            svc = json.loads(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
            st.session_state.firestore_db = firestore.Client.from_service_account_info(svc)
        return st.session_state.firestore_db

    # initialize flags (once)
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "chat_id" not in st.session_state:
        st.session_state.chat_id = str(uuid.uuid4())
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_title" not in st.session_state:
        st.session_state.chat_title = ""
    if "just_logged_in" not in st.session_state:
        st.session_state.just_logged_in = False

    # -------- NOT LOGGED IN: show auth only (no app UI) --------
    if not st.session_state.logged_in:
        config = load_config()
        menu = st.radio("Choose action", ["Login", "Sign Up"], key="auth_menu")

        if menu == "Sign Up":
            st.header("Create a New Account")
            with st.form("signup_form", clear_on_submit=True):
                new_username = st.text_input("Choose a username", key="su_user")
                new_password = st.text_input("Choose a password", type="password", key="su_pass")
                new_email    = st.text_input("Your email (optional)", key="su_email")
                did_signup   = st.form_submit_button("Sign Up")

            if did_signup:
                if not new_username or not new_password:
                    st.warning("Username and password required!")
                else:
                    db = get_db()
                    signup_user(new_username, new_password, new_email)
                    st.success("Account created! You can now log in.")
                    st.balloons()

        if menu == "Login":
            st.title("Login")
            with st.form("login_form", clear_on_submit=True):
                login_username = st.text_input("Username", key="li_user")
                login_password = st.text_input("Password", type="password", key="li_pass")
                did_login      = st.form_submit_button("Login")

            if did_login:
                db = get_db()
                success, user_data = authenticate_user(login_username, login_password)
                if success:
                    display_name = (
                        user_data.get("name")
                        or user_data.get("username")
                        or user_data.get("email")
                        or login_username
                    )
                    st.session_state.logged_in = True
                    st.session_state.user_id   = user_data.get("username") or login_username
                    st.session_state.just_logged_in = display_name
                    # clean inputs
                    for k in ("li_user", "li_pass"):
                        st.session_state.pop(k, None)
                    st.rerun()
                else:
                    st.error("Invalid username or password!")

        # back to home (still not logged in)
        if st.button("⬅️ Back to Home"):
            st.session_state.mode = None
            st.session_state.chat_history = []
            st.rerun()

        st.stop()  # prevent any app UI from rendering while not logged in

    # -------- LOGGED IN: app UI only (no auth UI) --------
    else:
        user_id = st.session_state.user_id
        db = get_db()

        # one-time toast after rerun
        if st.session_state.just_logged_in:
            st.success(f"Logged in as {st.session_state.just_logged_in}!")
            st.session_state.just_logged_in = False

        # MAIN AREA (title must NOT be in the sidebar)
        st.title("🤖 Gemini Chatbot")

        if st.button("🗑️ Clear Conversation", type="primary"):
            st.session_state.chat_history = []

        with st.form(key="chat_form", clear_on_submit=True):
            user_input = st.text_input("Type your message...", key="input_field")
            submitted = st.form_submit_button("Send")

        # render chat bubbles
        for chat in st.session_state.chat_history:
            if chat["role"] == "user":
                st.markdown(
                    f"""
                    <div style="display:flex; justify-content:flex-end; align-items:flex-end; margin:12px 0;">
                        <div style="background:#0078fe; color:white; padding:12px 18px; border-radius:16px 16px 2px 16px; margin-left:8px; max-width:70%; box-shadow:1px 2px 4px rgba(0,0,0,0.04); font-size:1.1em; word-break:break-word;">
                            {chat['text']}
                        </div>
                        <div style="margin-left:6px; font-size:1.6em;">🧑</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div style="display:flex; justify-content:flex-start; align-items:flex-end; margin:12px 0;">
                        <div style="margin-right:6px; font-size:1.6em;">🤖</div>
                        <div style="background:#f1f0f0; color:#222; padding:12px 18px; border-radius:16px 16px 16px 2px; margin-right:8px; max-width:70%; box-shadow:1px 2px 4px rgba(0,0,0,0.04); font-size:1.1em; word-break:break-word;">
                            {chat['text']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        # SIDEBAR (only sidebar items here)
        with st.sidebar:
            st.subheader(f"Signed in as **{user_id}**")
            if st.button("➕ New Chat"):
                st.session_state.chat_history = []
                st.session_state.chat_title = ""
                st.session_state.chat_id = str(uuid.uuid4())
                st.rerun()
            if st.button("🚪 Logout"):
                for k in ["logged_in", "user_id", "chat_id", "chat_history", "chat_title"]:
                    st.session_state.pop(k, None)
                st.rerun()

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
                                """,
                                unsafe_allow_html=True
                            )
        save_chat(
            user_id,
            st.session_state.chat_id,
            get_gemini_title(st.session_state.chat_history[:2]),
            st.session_state.chat_history,
        )


st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)
st.stop()