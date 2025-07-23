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
import streamlit as st
import streamlit_authenticator as stauth
from streamlit_oauth import login_button

#testing

# When user sends or receives a message, update Firestore:
def save_chat(user_id, chat_id, chat_title, messages):
    # If no title yet, fallback to first 30 chars of first message
    if not chat_title and messages:
        chat_title = messages[0]["text"][:30]
    chat_ref = db.collection('users').document(user_id).collection('chats').document(chat_id)
    chat_ref.set({
        'created_at': firestore.SERVER_TIMESTAMP,
        'title': chat_title,
        'messages': messages
    })

# To display previous chats in a sidebar
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

# Makes Gemini generate a title in 8 words and returns answer
def get_gemini_title(messages):
    # Construct a prompt from first 2 turns (user & Gemini)
    chat_content = "\n".join([f"{m['role']}: {m['text']}" for m in messages[:2]])
    prompt = (
        "Summarize this conversation so far with a short, descriptive title (max 8 words):\n"
        + chat_content
    )
    # Call Gemini again just for title
    return get_gemini_response(prompt).strip().replace('"','')

# Returns the Gemini response generated based on user question                 
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

# Verify the Firebase token
def verify_firebase_token(token):
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token  # Contains uid, email, etc.
    except Exception as e:
        st.error(f"Token verification error: {e}")
        return None

#deletes past chat
def delete_chat(user_id, chat_id):
    db.collection('users').document(user_id).collection('chats').document(chat_id).delete()
    
# Parse token from URL
query_params = st.query_params
# Make sure we handle both the case where it's a list or a string
id_token = None
if "token" in query_params:
    token_value = query_params["token"]
    if isinstance(token_value, list) and len(token_value) > 0:
        id_token = token_value[0]
    elif isinstance(token_value, str):
        id_token = token_value
# If we have a valid token, skip welcome screen and go to login flow
    if id_token:
        st.session_state.mode = "login"

#
GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
MS_CLIENT_ID = st.secrets["MS_CLIENT_ID"]
MS_CLIENT_SECRET = st.secrets["MS_CLIENT_SECRET"]

# Option to toggle guest or login
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
            # Redirect immediately to your login.html page (change port if needed)
            st.markdown("""
            <meta http-equiv="refresh" content="0; url='http://127.0.0.1:5500/login.html'" />
        """, unsafe_allow_html=True)
            st.rerun()
    with col2:
        if st.button("🚀 Continue as Guest"):
            st.session_state.mode = "guest"
            st.rerun()
    st.stop()

# ---------------------- Gemini API Config and App UI ----------------------

# Load Gemini API key from .env
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"

# -------------------------- GUEST MODE ------------------------------------
if st.session_state.mode == "guest":
    st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
    st.title("🤖 Gemini Chatbot (Guest Mode)")
    st.caption("Chat as a guest (your conversation will NOT be saved)")
    # Chat history for guest
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # --------------- Input Form & Display Chat History ----------------
    with st.form(key="chat_form_guest", clear_on_submit=True):
        user_input = st.text_input("Type your message...", key="input_field_guest")
        submitted = st.form_submit_button("Send")

    # Show chat history with bubbles
    for chat in st.session_state.chat_history:
        if chat["role"] == "user":
            # User message: right aligned
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
            # Gemini message: left aligned
            st.markdown(
                f"""
                <div style="display: flex; justify-content: flex-start; align-items: flex-end; margin: 12px 0;">
                    <div style="margin-right: 6px; font-size: 1.6em;">🤖</div>
                    <div style="background: #f1f0f0; color: #222; padding: 12px 18px; border-radius: 16px 16px 16px 2px; margin-right: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                        {chat['text']}
                """,
                unsafe_allow_html=True)

    # When user submits a message
    if submitted and user_input:
        # Animate the user's typing bubble
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

        # Now add user message to chat history
        st.session_state.chat_history.append({"role": "user", "text": user_input})

        # Animate Gemini's typing bubble
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

        # Now add Gemini's response to chat history
        st.session_state.chat_history.append({"role": "gemini", "text": bot_response})
        st.rerun()

    # Guest: Back to Home button
    if st.button("⬅️ Back to Home"):
        st.session_state.mode = None
        st.session_state.chat_history = []
        st.rerun()
    st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)
    st.stop()

# ---------------------- LOGIN/AUTH/FIRESTORE MODE ---------------------------
if st.session_state.mode == "login":

    user_info = login_button(
        provider="google",  # Can be "google" or "microsoft"
        client_id=st.secrets["GOOGLE_CLIENT_ID"],     # or MS_CLIENT_ID if "microsoft"
        client_secret=st.secrets["GOOGLE_CLIENT_SECRET"],  # or MS_CLIENT_SECRET
        key="user_oauth",  # Session key
        redirect_uri=None,  # For Streamlit Cloud, you can leave as None
        scopes=["openid", "email", "profile"]
    )

    if user_info:
        st.success(f"Logged in as {user_info['email']}")
        user_id = user_info["email"]  # Use email as user_id for Firestore
        # Initialize Firestore client if not already done
        if not hasattr(st, 'firestore_db'):
            service_account_info = json.loads(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
            st.firestore_db = firestore.Client.from_service_account_info(service_account_info)
        db = st.firestore_db


    # -------------------- SIDEBAR: Past Chats & New Chat Button --------------------

    # Keep sidebar state consistent across reruns
    if "chat_id" not in st.session_state:
        st.session_state.chat_id = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_title" not in st.session_state:
        st.session_state.chat_title = ""

    #logout button
    if st.sidebar.button("🚪 Logout"):
        # Clear all session state variables relevant to user and chat
        for key in ["chat_id", "chat_history", "chat_title", "mode"]:
            if key in st.session_state:
                del st.session_state[key]
        st.markdown("""
    <meta http-equiv="refresh" content="0; url='http://localhost:8501/'" />
    """, unsafe_allow_html=True)
        st.stop()

    st.sidebar.header("Past Chats")
    # New chat button: resets state and creates new chat ID
    if st.sidebar.button("➕ New Chat"):
        st.session_state.chat_history = []
        st.session_state.chat_id = str(uuid.uuid4())
        st.session_state.chat_title = ""
        st.rerun()

    # List all past chats, show Gemini-generated title
    chat_summaries = list_user_chats(user_id)
    for chat in chat_summaries:
        chat_col, del_col = st.sidebar.columns([6, 1])
        with chat_col:
            if st.button(chat['title'], key=chat['id']):
                # Load messages and title from Firestore into session state
                st.session_state.chat_id = chat['id']
                st.session_state.chat_history = chat['messages']
                st.session_state.chat_title = chat['title']
                st.rerun()
        with del_col:
            if st.button("🗑️", key="del_" + chat['id']):
                delete_chat(user_id, chat['id'])
                # If the deleted chat is currently open, clear it from session
                if st.session_state.get("chat_id") == chat['id']:
                    st.session_state.chat_id = None
                    st.session_state.chat_history = []
                    st.session_state.chat_title = ""
                st.rerun()


    # Streamlit Page Config & Styling
    st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
    st.title("🤖 Gemini Chatbot")

    # Clear conversation button
    if st.button("🗑️ Clear Conversation", type="primary"):
        st.session_state.chat_history = []

# --------------- Input Form & Display Chat History ----------------

with st.form(key="chat_form", clear_on_submit=True):
    user_input = st.text_input("Type your message...", key="input_field")
    submitted = st.form_submit_button("Send")

# Show chat history
for chat in st.session_state.chat_history:
    if chat["role"] == "user":
        # User message: right aligned
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
        # Gemini message: left aligned
        st.markdown(
            f"""
            <div style="display: flex; justify-content: flex-start; align-items: flex-end; margin: 12px 0;">
                <div style="margin-right: 6px; font-size: 1.6em;">🤖</div>
                <div style="background: #f1f0f0; color: #222; padding: 12px 18px; border-radius: 16px 16px 16px 2px; margin-right: 8px; max-width: 70%; box-shadow: 1px 2px 4px rgba(0,0,0,0.04); font-size: 1.1em; word-break: break-word;">
                    {chat['text']}
            """,
            unsafe_allow_html=True)

# When user submits a message
if submitted and user_input:
    # Animate the user's typing bubble
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

    # Now add user message to chat history
    st.session_state.chat_history.append({"role": "user", "text": user_input})

    # Animate Gemini's typing bubble
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

    # Now add Gemini's response to chat history
    st.session_state.chat_history.append({"role": "gemini", "text": bot_response})

    # Use or create a unique chat_id for the session
    if not st.session_state.get("chat_id"):
        st.session_state.chat_id = str(uuid.uuid4())
    chat_id = st.session_state.chat_id

    # Generate Gemini chat title if needed, after first exchange
    # Only create title if not already set or it's the default
    if (not st.session_state.get("chat_title") or st.session_state["chat_title"] == "Conversation with Gemini") and len(st.session_state.chat_history) >= 2:
        gemini_title = get_gemini_title(st.session_state.chat_history[:2])
        st.session_state["chat_title"] = gemini_title
    else:
        gemini_title = st.session_state.get("chat_title", "")

    # Save chat to Firestore
    save_chat(user_id, chat_id, gemini_title, st.session_state.chat_history)
    st.rerun()

st.markdown("<div style='height:15vh'></div>", unsafe_allow_html=True)