import asyncio
import json
import os
import re
import uuid
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
from dotenv import load_dotenv
from livekit import api

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env.local")

# On Streamlit Community Cloud, secrets are only exposed via st.secrets, not
# as OS environment variables, but the LiveKit SDK reads its config from the
# environment. Mirror them over when present.
for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
    if key in st.secrets:
        os.environ[key] = st.secrets[key]

st.set_page_config(page_title="Nalia Tester", page_icon="📞")

# Authentication. Credentials live in st.secrets (see
# .streamlit/secrets.toml.example) rather than a committed file, so password
# hashes never end up in git.
auth_cfg = st.secrets["auth"]
credentials = {
    "usernames": {
        username: dict(user)
        for username, user in auth_cfg["credentials"]["usernames"].items()
    }
}
authenticator = stauth.Authenticate(
    credentials,
    auth_cfg["cookie_name"],
    auth_cfg["cookie_key"],
    auth_cfg["cookie_expiry_days"],
)

authenticator.login()

if st.session_state.get("authentication_status") is False:
    st.error("Email/password inválidos.")
    st.stop()
if st.session_state.get("authentication_status") is None:
    st.info("Faz login para continuares.")
    st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.success(f"Logado como: {st.session_state.get('name')}")

AGENT_NAME = "zelai"
PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")  # E.164

PRESETS = [
    ("Rafa", "+351967872718"),
    ("Luís", "+351964192119"),
    ("Dani", "+351932587940"),
]


async def hang_up_active_calls() -> int:
    """Delete any rooms this app dialed, disconnecting the calls immediately."""
    async with api.LiveKitAPI() as lk:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
        call_rooms = [r for r in rooms if r.name.startswith("call-")]
        for r in call_rooms:
            await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
    return len(call_rooms)


def stop_calls() -> None:
    try:
        hung_up = asyncio.run(hang_up_active_calls())
        st.success(f"Chamadas terminadas: {hung_up}.")
    except Exception as e:
        st.error(f"Falha ao desligar chamadas ativas: {e}")


async def hang_up_calls_for_number(phone_number: str) -> int:
    """Delete any rooms already in progress for this number, so a new dispatch
    can't join a stale room left over from a previous test call."""
    prefix = f"call-{phone_number.lstrip('+')}-"
    async with api.LiveKitAPI() as lk:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
        matching = [r for r in rooms if r.name.startswith(prefix)]
        for r in matching:
            await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
    return len(matching)


async def dispatch_call(phone_number: str) -> api.AgentDispatch:
    # Suffix with a unique id so repeated calls to the same number never
    # reuse a room a previous (possibly still-lingering) call was using.
    room_name = f"call-{phone_number.lstrip('+')}-{uuid.uuid4().hex[:8]}"
    async with api.LiveKitAPI() as lk:
        return await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=json.dumps({"phone_number": phone_number}),
            )
        )


def place_call(phone_number: str) -> None:
    phone_number = re.sub(r"\s+", "", phone_number)
    if not PHONE_RE.match(phone_number):
        st.error("Use o formato internacional E.164, por exemplo +351912345678.")
        return
    try:
        with st.spinner(f"A chamar {phone_number}..."):
            asyncio.run(hang_up_calls_for_number(phone_number))
            dispatch = asyncio.run(dispatch_call(phone_number))
        st.success(f"Chamada iniciada. Sala: {dispatch.room}")
    except Exception as e:
        st.error(f"Falha ao iniciar a chamada: {e}")


st.title("Nalia Tester")
st.caption(
    "Escolha um contacto ou introduza um número novo. "
    "Requer que o agente já esteja implementado e à escuta no LiveKit."
)

cols = st.columns(len(PRESETS))
for col, (name, number) in zip(cols, PRESETS):
    with col:
        if st.button(f"📞 {name}", use_container_width=True):
            place_call(number)

st.divider()

phone_number = st.text_input("Novo número", placeholder="+351912345678")
if st.button("Ligar", type="primary"):
    if not phone_number:
        st.error("Introduza um número de telefone.")
    else:
        place_call(phone_number)

st.divider()
if st.button("🛑 Terminar chamadas ativas"):
    stop_calls()