"""
streamlit_app.py
Small UI to generate a CS2 widget URL from nickname (steamid64 and match_id optional).
"""

from urllib.parse import urlencode

import streamlit as st


DEFAULT_WIDGET_URL = "http://127.0.0.1:5500/index.html"


def build_widget_url(base_url: str, nickname: str, steamid64: str, match_id: str) -> str:
    params = {"nickname": nickname.strip()}
    if steamid64.strip():
        params["steamid64"] = steamid64.strip()
    if match_id.strip():
        params["match_id"] = match_id.strip()

    query = urlencode(params)
    clean_base = base_url.strip().rstrip("?&")
    separator = "&" if "?" in clean_base else "?"
    return f"{clean_base}{separator}{query}"


def main() -> None:
    st.set_page_config(page_title="CS2 Widget Builder", page_icon="C", layout="centered")
    st.title("CS2 Widget Builder")
    st.caption("Fill fields, generate the widget URL, then open it with one click.")
    st.caption("SteamID64 is optional: the widget can resolve it automatically from Faceit nickname.")
    st.caption("Match ID is optional: the backend now tries automatic live match detection from nickname.")

    with st.form("widget_form"):
        base_url = st.text_input("Widget base URL", value=DEFAULT_WIDGET_URL)
        nickname = st.text_input("Faceit nickname", value="")
        steamid64 = st.text_input("SteamID64 (optional, auto if empty)", value="")
        match_id = st.text_input("Match ID (optional, auto if empty)", value="")
        submitted = st.form_submit_button("Create widget")

    if not submitted:
        return

    nickname = nickname.strip()
    steamid64 = steamid64.strip()
    base_url = base_url.strip()
    match_id = match_id.strip()

    errors = []
    if not base_url:
        errors.append("Widget base URL is required.")
    if not nickname:
        errors.append("Faceit nickname is required.")

    if errors:
        for error in errors:
            st.error(error)
        return

    widget_url = build_widget_url(base_url, nickname, steamid64, match_id)

    st.success("Widget URL generated.")
    st.code(widget_url, language="text")
    st.link_button("Open widget", widget_url, type="primary")

    st.info(
        "Reminder: keep your local servers running (proxy + static file server) before opening the widget."
    )


if __name__ == "__main__":
    main()
