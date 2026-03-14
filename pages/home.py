import streamlit as st


st.title("Home")
st.write("Wähle die Funktion, die du für deine SEPA-Datei brauchst.")

st.markdown(
    """
    <style>
    .home-cards {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
        margin-top: 1rem;
    }
    .home-card {
        display: block;
        height: 100%;
        padding: 1.4rem 1.5rem;
        border: 1px solid rgba(49, 51, 63, 0.2);
        border-radius: 0.75rem;
        text-decoration: none;
        color: inherit;
        background: rgba(255, 255, 255, 0.02);
        transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
    }
    .home-card:hover {
        border-color: #ff4b4b;
        box-shadow: 0 0 0 1px rgba(255, 75, 75, 0.2);
        transform: translateY(-2px);
    }
    .home-card h3 {
        margin: 0 0 0.75rem 0;
        font-size: 1.25rem;
    }
    .home-card p {
        margin: 0;
        line-height: 1.5;
    }
    @media (max-width: 900px) {
        .home-cards {
            grid-template-columns: 1fr;
        }
    }
    </style>
    <div class="home-cards">
        <a class="home-card" href="/lastschrift" target="_self">
            <h3>Sammellastschrift</h3>
            <p>Ein Konto zieht mehrere Lastschriften bei verschiedenen Personen oder Organisationen ein.</p>
        </a>
        <a class="home-card" href="/ueberweisung" target="_self">
            <h3>Sammelüberweisung</h3>
            <p>Ein Konto überweist mehrere Beträge an verschiedene Empfängerinnen und Empfänger.</p>
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)
