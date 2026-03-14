from pathlib import Path
import datetime as dt
import re
import xml.dom.minidom
import xml.etree.ElementTree as ET

import pandas as pd
from sepaxml import SepaDD
from sepaxml.validation import ValidationError
import streamlit as st


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "dummy_lastschrift.xlsx"
NS = {"ns": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"}


class InputFileError(ValueError):
    pass


IBAN_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
BIC_PATTERN = re.compile(r"^[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$")


def read_uploaded_workbook(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        workbook = pd.read_excel(uploaded_file, sheet_name=["config", "payments"])
    except ValueError as exc:
        raise InputFileError(
            "Die Excel-Datei muss die Blätter `payments` und `config` enthalten. "
            "Im Blatt `payments` stehen die einzelnen Lastschriften. Im Blatt `config` stehen die "
            "Kontodaten des Gläubigers."
        ) from exc
    return workbook["config"], workbook["payments"]


def validate_columns(df: pd.DataFrame, required_columns: dict[str, str], sheet_name: str) -> None:
    missing_columns = [column for column in required_columns if column not in df.columns]
    if not missing_columns:
        return

    details = " ".join(
        f"`{column}`: {required_columns[column]}" for column in missing_columns
    )
    raise InputFileError(
        f"Im Blatt `{sheet_name}` fehlen Pflichtspalten: {', '.join(f'`{column}`' for column in missing_columns)}. "
        f"Diese Angaben werden zwingend erwartet. {details}"
    )


def validate_non_empty(df: pd.DataFrame, sheet_name: str) -> None:
    if df.empty:
        raise InputFileError(
            f"Das Blatt `{sheet_name}` ist leer. Dort müssen Daten stehen, damit die App eine SEPA-Lastschriftdatei erzeugen kann."
        )


def validate_workbook(df_config: pd.DataFrame, df_payments: pd.DataFrame) -> None:
    validate_non_empty(df_config, "config")
    validate_non_empty(df_payments, "payments")
    validate_columns(
        df_config,
        {
            "name": "Der Name wird als Gläubiger in die XML geschrieben.",
            "IBAN": "Die IBAN legt fest, auf welches Konto eingezogen wird.",
            "batch": "Diese Angabe steuert, ob die Lastschriften als Sammelbuchung geschrieben werden.",
            "creditor_id": "Die Gläubiger-ID ist für SEPA-Lastschriften verpflichtend.",
            "currency": "Die Währung wird für die Beträge in der XML benötigt.",
        },
        "config",
    )
    validate_columns(
        df_payments,
        {
            "Vorname": "Vorname und Nachname werden zum Namen des Zahlungspflichtigen zusammengesetzt.",
            "Name": "Vorname und Nachname werden zum Namen des Zahlungspflichtigen zusammengesetzt.",
            "IBAN": "Die IBAN gibt das Konto an, von dem eingezogen wird.",
            "amount": "Der Betrag legt fest, wie viel eingezogen wird.",
            "mandate_id": "Die Mandatsreferenz ist für eine gültige Lastschrift zwingend nötig.",
            "mandate_date": "Das Mandatsdatum dokumentiert, wann das SEPA-Mandat erteilt wurde.",
            "description": "Der Verwendungszweck wird in die XML geschrieben.",
        },
        "payments",
    )


def parse_batch(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "ja", "y"}


def normalize_iban(value) -> str:
    return str(value).replace(" ", "").strip().upper()


def normalize_bic(value) -> str | None:
    if pd.isna(value):
        return None
    bic = str(value).replace(" ", "").strip().upper()
    return bic or None


def require_text(value, field_label: str, why: str, row_number: int | None = None) -> str:
    if pd.isna(value) or not str(value).strip():
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(f"Das Feld `{field_label}` fehlt{location}. {why}")
    return str(value).strip()


def validate_iban(value, field_label: str, why: str, row_number: int | None = None) -> str:
    iban = normalize_iban(value)
    if not IBAN_PATTERN.fullmatch(iban):
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Die IBAN im Feld `{field_label}` ist{location} ungültig: `{value}`. {why}"
        )
    return iban


def validate_bic(value, field_label: str, why: str, row_number: int | None = None) -> str | None:
    bic = normalize_bic(value)
    if bic is None:
        return None
    if not BIC_PATTERN.fullmatch(bic):
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Der BIC im Feld `{field_label}` ist{location} ungültig: `{value}`. {why}"
        )
    return bic


def validate_amount(value, field_label: str, why: str, row_number: int | None = None) -> int:
    try:
        amount = float(value)
    except Exception as exc:
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Der Betrag im Feld `{field_label}` ist{location} keine Zahl: `{value}`. {why}"
        ) from exc
    if amount <= 0:
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Der Betrag im Feld `{field_label}` muss{location} größer als 0 sein. {why}"
        )
    return int(round(amount * 100))


def validate_date(value, field_label: str, why: str, row_number: int | None = None) -> dt.date:
    try:
        parsed = pd.to_datetime(value)
    except Exception as exc:
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Das Datum im Feld `{field_label}` ist{location} ungültig: `{value}`. {why}"
        ) from exc
    if pd.isna(parsed):
        location = f" in Zeile {row_number}" if row_number is not None else ""
        raise InputFileError(
            f"Das Datum im Feld `{field_label}` fehlt{location}. {why}"
        )
    return parsed.date()


def format_schema_validation_error(exc: ValidationError) -> str:
    cause = exc.__cause__
    if cause is None:
        return str(exc)

    path = getattr(cause, "path", "") or ""
    value = getattr(cause, "obj", None)
    reason = getattr(cause, "reason", "") or ""

    field_label = "ein Eingabefeld"
    why = "Dieser Wert wird für eine gültige SEPA-Lastschriftdatei benötigt."
    if path.endswith("/CdtrAgt/FinInstnId/BIC"):
        field_label = "BIC des Gläubigers"
        why = "Der BIC identifiziert die Bank des Gläubigers."
    elif path.endswith("/DbtrAgt/FinInstnId/BIC"):
        field_label = "BIC eines Zahlungspflichtigen"
        why = "Der BIC identifiziert die Bank des Zahlungspflichtigen."
    elif path.endswith("/CdtrAcct/Id/IBAN"):
        field_label = "IBAN des Gläubigers"
        why = "Die IBAN legt fest, auf welches Konto eingezogen wird."
    elif path.endswith("/DbtrAcct/Id/IBAN"):
        field_label = "IBAN eines Zahlungspflichtigen"
        why = "Die IBAN legt fest, von welchem Konto eingezogen wird."
    elif path.endswith("/ReqdColltnDt"):
        field_label = "Einzugsdatum"
        why = "Die Bank braucht dieses Datum, um die Lastschrift terminieren zu können."
    elif path.endswith("/MndtId"):
        field_label = "Mandatsreferenz"
        why = "Die Mandatsreferenz ist bei SEPA-Lastschriften verpflichtend."
    elif path.endswith("/DtOfSgntr"):
        field_label = "Mandatsdatum"
        why = "Das Mandatsdatum dokumentiert die Erteilung des SEPA-Mandats."
    elif path.endswith("/Ustrd"):
        field_label = "Verwendungszweck"
        why = "Der Verwendungszweck wird in die XML übernommen."
    elif path.endswith("/Nm"):
        field_label = "Name"
        why = "Der Name wird in die XML für Gläubiger oder Zahlungspflichtige geschrieben."

    value_text = f" Der problematische Wert ist `{value}`." if value not in (None, "") else ""
    reason_text = f" Technischer Grund: {reason}" if reason else ""
    return f"Ungültiger Wert im Feld {field_label}.{value_text} {why}{reason_text}"


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
    validate_workbook(df_config, df_payments)

    config = {
        "name": require_text(
            df_config.loc[0, "name"],
            "name",
            "Der Name wird als Gläubiger in die XML geschrieben.",
        ),
        "IBAN": validate_iban(
            df_config.loc[0, "IBAN"],
            "IBAN",
            "Diese IBAN ist nötig, damit das Zielkonto des Einzugs eindeutig ist.",
        ),
        "batch": parse_batch(df_config.loc[0, "batch"]),
        "creditor_id": require_text(
            df_config.loc[0, "creditor_id"],
            "creditor_id",
            "Die Gläubiger-ID ist für SEPA-Lastschriften verpflichtend.",
        ),
        "currency": require_text(
            df_config.loc[0, "currency"],
            "currency",
            "Die Währung wird für die Beträge in der XML benötigt.",
        ),
    }

    config_bic = validate_bic(
        df_config.loc[0, "BIC"],
        "BIC",
        "Wenn ein BIC angegeben wird, muss er dem Bankformat entsprechen.",
    )
    if config_bic:
        config["BIC"] = config_bic

    sepa = SepaDD(config, clean=True)
    preview_rows = []

    for row_number, (_, row) in enumerate(df_payments.iterrows(), start=1):
        payment = {
            "name": compose_name(row),
            "IBAN": validate_iban(
                row["IBAN"],
                "IBAN",
                "Diese IBAN ist nötig, damit das belastete Konto eindeutig ist.",
                row_number,
            ),
            "amount": validate_amount(
                row["amount"],
                "amount",
                "Der Betrag ist nötig, damit die Lastschrift korrekt erstellt wird.",
                row_number,
            ),
            "type": str(row.get("type", "RCUR")).strip(),
            "collection_date": validate_date(
                row.get("collection_date", dt.date.today()),
                "collection_date",
                "Das Einzugsdatum legt fest, wann die Lastschrift eingereicht werden soll.",
                row_number,
            ),
            "mandate_id": require_text(
                row["mandate_id"],
                "mandate_id",
                "Die Mandatsreferenz ist für eine gültige Lastschrift zwingend nötig.",
                row_number,
            ),
            "mandate_date": validate_date(
                row["mandate_date"],
                "mandate_date",
                "Das Mandatsdatum dokumentiert, wann das SEPA-Mandat erteilt wurde.",
                row_number,
            ),
            "description": require_text(
                row["description"],
                "description",
                "Der Verwendungszweck wird in die XML übernommen.",
                row_number,
            ),
        }

        payment_bic = validate_bic(
            row.get("BIC"),
            "BIC",
            "Wenn ein BIC angegeben wird, muss er dem Bankformat entsprechen.",
            row_number,
        )
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
    except InputFileError as exc:
        st.error(str(exc))
    except ValidationError as exc:
        st.error(format_schema_validation_error(exc))
    except Exception as exc:
        st.error(
            "Die Excel-Datei konnte nicht verarbeitet werden. "
            f"Bitte prüfe insbesondere Datumswerte, Beträge, Mandatsangaben und IBANs. Technischer Hinweis: {exc}"
        )
