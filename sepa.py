import streamlit as st


st.set_page_config(page_title="SEPA XML Generator", layout="wide")

navigation = st.navigation(
    [
        st.Page("pages/home.py", title="Home", url_path="", default=True),
        st.Page("pages/lastschrift.py", title="Sammellastschrift", url_path="lastschrift"),
        st.Page("pages/ueberweisung.py", title="Sammelüberweisung", url_path="ueberweisung"),
    ]
)
navigation.run()
