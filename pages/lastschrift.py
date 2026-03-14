from pathlib import Path
import datetime as dt
import xml.dom.minidom
import xml.etree.ElementTree as ET

import pandas as pd
from sepaxml import SepaDD
import streamlit as st


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "dummy_lastschrift.xlsx"
NS = {"ns": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"}


def read_uploaded_workbook(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    workbook = pd.read_excel(uploaded_file, sheet_name=["config", "payments"])
    return workbook["config"], workbook["payments"]


def parse_batch(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "ja", "y"}


def normalize_iban(value) -> str:
    return str(value).replace(" ", "").strip()


def normalize_bic(value) -> str | None:
    if pd.isna(value):
        return None
    bic = str(value).replace(" ", "").strip()
    return bic or None


def compose_name(row: pd.Series) -> str:
    first_name = str(row.get("Vorname", "")).strip() if pd.notna(row.get("Vorname")) else ""
    last_name = str(row.get("Name", "")).strip() if pd.notna(row.get("Name")) else ""
    full_name = " ".join(part for part in (first_name, last_name) if part)
    if not full_name:
        raise ValueError("In einer Zahlungszeile fehlt der Name.")
    return full_name


def to_cent_amount(value) -> int:
    return int(round(float(value) * 100))


def to_date(value) -> dt.date:
    return pd.to_datetime(value).date()


def format_xml(xml_content: bytes) -> str:
    return xml.dom.minidom.parseString(xml_content).toprettyxml()


def summarize_xml(xml_content: bytes) -> pd.DataFrame:
    root = ET.fromstring(xml_content)
    payment_info = root.find(".//ns:PmtInf", NS)

    summary_rows = [
        {
            "Feld": "Nachrichten-ID",
            "Wert": root.findtext(".//ns:GrpHdr/ns:MsgId", default="", namespaces=NS),
        },
        {
            "Feld": "Anzahl Lastschriften",
            "Wert": root.findtext(".//ns:GrpHdr/ns:NbOfTxs", default="", namespaces=NS),
        },
        {
            "Feld": "Gesamtsumme",
            "Wert": root.findtext(".//ns:GrpHdr/ns:CtrlSum", default="", namespaces=NS),
        },
        {
            "Feld": "Gläubiger",
            "Wert": payment_info.findtext("ns:Cdtr/ns:Nm", default="", namespaces=NS)
            if payment_info is not None
            else "",
        },
        {
            "Feld": "Konto",
            "Wert": payment_info.findtext("ns:CdtrAcct/ns:Id/ns:IBAN", default="", namespaces=NS)
            if payment_info is not None
            else "",
        },
        {
            "Feld": "Einzugsdatum",
            "Wert": payment_info.findtext("ns:ReqdColltnDt", default="", namespaces=NS)
            if payment_info is not None
            else "",
        },
    ]
    return pd.DataFrame(summary_rows)


def build_document(df_config: pd.DataFrame, df_payments: pd.DataFrame) -> tuple[bytes, pd.DataFrame]:
    config = {
        "name": str(df_config.loc[0, "name"]).strip(),
        "IBAN": normalize_iban(df_config.loc[0, "IBAN"]),
        "batch": parse_batch(df_config.loc[0, "batch"]),
        "creditor_id": str(df_config.loc[0, "creditor_id"]).strip(),
        "currency": str(df_config.loc[0, "currency"]).strip(),
    }

    config_bic = normalize_bic(df_config.loc[0, "BIC"])
    if config_bic:
        config["BIC"] = config_bic

    sepa = SepaDD(config, clean=True)
    preview_rows = []

    for _, row in df_payments.iterrows():
        payment = {
            "name": compose_name(row),
            "IBAN": normalize_iban(row["IBAN"]),
            "amount": to_cent_amount(row["amount"]),
            "type": str(row.get("type", "RCUR")).strip(),
            "collection_date": to_date(row.get("collection_date", dt.date.today())),
            "mandate_id": str(row["mandate_id"]).strip(),
            "mandate_date": to_date(row["mandate_date"]),
            "description": str(row["description"]).strip(),
        }

        payment_bic = normalize_bic(row.get("BIC"))
        if payment_bic:
            payment["BIC"] = payment_bic

        sepa.add_payment(payment)
        preview_rows.append(
            {
                "Name": payment["name"],
                "IBAN": payment["IBAN"],
                "Betrag (EUR)": payment["amount"] / 100,
                "Typ": payment["type"],
                "Mandatsreferenz": payment["mandate_id"],
                "Beschreibung": payment["description"],
            }
        )

    return sepa.export(validate=True), pd.DataFrame(preview_rows)


st.title("SEPA Sammellastschrift")
st.write("Erzeuge eine XML-Datei für mehrere Lastschriften in einem Schritt.")

with st.expander("Hilfe zur Eingabedatei"):
    st.write(
        "Die Excel-Datei braucht zwei Tabellenblätter. Im Blatt `config` steht genau eine Zeile mit "
        "den Daten des Kontos, das die Lastschriften einzieht. Im Blatt `payments` steht pro Zeile eine "
        "einzelne Lastschrift."
    )
    st.write(
        "Die Reihenfolge der beiden Blätter ist egal. Auch die Reihenfolge der Spalten ist egal, solange "
        "die benötigten Spaltennamen vorhanden sind. Zusätzliche Spalten werden einfach ignoriert."
    )
    st.write(
        "Im Zahlungsblatt werden Name, IBAN, Betrag, Mandatsreferenz, Mandatsdatum und ein kurzer "
        "Verwendungszweck erwartet. Optional kannst du auch BIC, Lastschrift-Typ und Einzugsdatum angeben."
    )
    st.write(
        "Wenn du keinen BIC angibst, wird er in der XML-Datei weggelassen. Das ist bei vielen SEPA-Fällen "
        "in Ordnung, kann aber je nach Bank oder Sonderfall trotzdem Probleme machen."
    )
    st.write(
        "Wenn du keinen Lastschrift-Typ angibst, verwendet die App automatisch `RCUR` für eine wiederkehrende "
        "Folgelastschrift."
    )
    st.write(
        "Wenn du kein Einzugsdatum angibst, setzt die App automatisch das heutige Datum ein. Das ist praktisch "
        "zum Testen, für echte Dateien solltest du das Datum bewusst festlegen."
    )
    st.download_button(
        label="Vorlage herunterladen",
        data=TEMPLATE_PATH.read_bytes(),
        file_name=TEMPLATE_PATH.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dd_template_download",
    )

uploaded_file = st.file_uploader("Excel-Datei hochladen", type="xlsx", key="dd_upload")

if uploaded_file is not None:
    try:
        df_config, df_payments = read_uploaded_workbook(uploaded_file)
        xml_content, df_preview = build_document(df_config, df_payments)
        df_summary = summarize_xml(xml_content)

        left_col, right_col = st.columns([2, 1])
        with left_col:
            st.subheader("Einzelne Zahlungen")
            st.dataframe(df_preview, use_container_width=True)
        with right_col:
            st.subheader("Sammeldaten aus der XML")
            st.dataframe(df_summary, hide_index=True, use_container_width=True)

        st.download_button(
            label="SEPA-XML-Datei herunterladen",
            data=xml_content,
            file_name="sepa_lastschrift.xml",
            mime="application/xml",
        )
        st.subheader("SEPA XML Vorschau")
        st.code(format_xml(xml_content), language="xml")
    except Exception as exc:
        st.error(f"Fehler bei der Verarbeitung der Excel-Datei: {exc}")
