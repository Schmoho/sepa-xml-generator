from pathlib import Path
import datetime as dt
import re
import xml.dom.minidom
import xml.etree.ElementTree as ET

import pandas as pd
from sepaxml import SepaTransfer
from sepaxml.validation import ValidationError
import streamlit as st


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "dummy_ueberweisung.xlsx"
NS = {"ns": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"}


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
            "Im Blatt `payments` stehen die einzelnen Überweisungen. Im Blatt `config` stehen die "
            "Kontodaten des Auftraggebers."
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
            f"Das Blatt `{sheet_name}` ist leer. Dort müssen Daten stehen, damit die App eine SEPA-Überweisungsdatei erzeugen kann."
        )


def validate_workbook(df_config: pd.DataFrame, df_payments: pd.DataFrame) -> None:
    validate_non_empty(df_config, "config")
    validate_non_empty(df_payments, "payments")
    validate_columns(
        df_config,
        {
            "name": "Der Name wird als Auftraggeber in die XML geschrieben.",
            "IBAN": "Die IBAN legt fest, von welchem Konto überwiesen wird.",
            "batch": "Diese Angabe steuert, ob die Überweisungen als Sammelbuchung geschrieben werden.",
            "currency": "Die Währung wird für die Beträge in der XML benötigt.",
        },
        "config",
    )
    validate_columns(
        df_payments,
        {
            "Vorname": "Vorname und Nachname werden zum Namen des Zahlungsempfängers zusammengesetzt.",
            "Name": "Vorname und Nachname werden zum Namen des Zahlungsempfängers zusammengesetzt.",
            "IBAN": "Die IBAN gibt das Zielkonto der Überweisung an.",
            "amount": "Der Betrag legt fest, wie viel überwiesen wird.",
            "execution_date": "Das Ausführungsdatum wird benötigt, weil die Bank wissen muss, wann die Überweisung ausgeführt werden soll.",
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
    why = "Dieser Wert wird für eine gültige SEPA-Überweisungsdatei benötigt."
    if path.endswith("/DbtrAgt/FinInstnId/BIC"):
        field_label = "BIC des Auftraggebers"
        why = "Der BIC identifiziert die Bank des Auftraggebers."
    elif path.endswith("/CdtrAgt/FinInstnId/BIC"):
        field_label = "BIC eines Zahlungsempfängers"
        why = "Der BIC identifiziert die Bank des Zahlungsempfängers."
    elif path.endswith("/DbtrAcct/Id/IBAN"):
        field_label = "IBAN des Auftraggebers"
        why = "Die IBAN legt fest, von welchem Konto überwiesen wird."
    elif path.endswith("/CdtrAcct/Id/IBAN"):
        field_label = "IBAN eines Zahlungsempfängers"
        why = "Die IBAN legt fest, auf welches Konto überwiesen wird."
    elif path.endswith("/ReqdExctnDt"):
        field_label = "Ausführungsdatum"
        why = "Die Bank braucht dieses Datum, um die Überweisung terminieren zu können."
    elif path.endswith("/Ustrd"):
        field_label = "Verwendungszweck"
        why = "Der Verwendungszweck wird in die XML übernommen."
    elif path.endswith("/Nm"):
        field_label = "Name"
        why = "Der Name wird in die XML für Auftraggeber oder Empfänger geschrieben."

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


def generate_endtoend_id(execution_date: dt.date, row_number: int) -> str:
    return f"TRF-{execution_date:%Y%m%d}-{row_number:04d}"


def summarize_xml(xml_content: bytes) -> pd.DataFrame:
    root = ET.fromstring(xml_content)
    payment_info = root.find(".//ns:PmtInf", NS)

    summary_rows = [
        {
            "Feld": "Nachrichten-ID",
            "Wert": root.findtext(".//ns:GrpHdr/ns:MsgId", default="", namespaces=NS),
        },
        {
            "Feld": "Anzahl Überweisungen",
            "Wert": root.findtext(".//ns:GrpHdr/ns:NbOfTxs", default="", namespaces=NS),
        },
        {
            "Feld": "Gesamtsumme",
            "Wert": root.findtext(".//ns:GrpHdr/ns:CtrlSum", default="", namespaces=NS),
        },
        {
            "Feld": "Auftraggeber",
            "Wert": payment_info.findtext("ns:Dbtr/ns:Nm", default="", namespaces=NS)
            if payment_info is not None
            else "",
        },
        {
            "Feld": "Konto",
            "Wert": payment_info.findtext("ns:DbtrAcct/ns:Id/ns:IBAN", default="", namespaces=NS)
            if payment_info is not None
            else "",
        },
        {
            "Feld": "Ausführungsdatum",
            "Wert": payment_info.findtext("ns:ReqdExctnDt", default="", namespaces=NS)
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
            "Der Name wird als Auftraggeber in die XML geschrieben.",
        ),
        "IBAN": validate_iban(
            df_config.loc[0, "IBAN"],
            "IBAN",
            "Diese IBAN ist nötig, damit die XML das belastete Konto eindeutig angibt.",
        ),
        "batch": parse_batch(df_config.loc[0, "batch"]),
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

    sepa = SepaTransfer(config, clean=True)
    preview_rows = []

    for row_number, (_, row) in enumerate(df_payments.iterrows(), start=1):
        execution_date = validate_date(
            row["execution_date"],
            "execution_date",
            "Das Ausführungsdatum legt fest, wann die Überweisung ausgeführt wird.",
            row_number,
        )
        payment = {
            "name": compose_name(row),
            "IBAN": validate_iban(
                row["IBAN"],
                "IBAN",
                "Diese IBAN ist nötig, damit das Zielkonto eindeutig ist.",
                row_number,
            ),
            "amount": validate_amount(
                row["amount"],
                "amount",
                "Der Betrag ist nötig, damit die Überweisung korrekt erstellt wird.",
                row_number,
            ),
            "execution_date": execution_date,
            "description": require_text(
                row["description"],
                "description",
                "Der Verwendungszweck wird in die XML übernommen.",
                row_number,
            ),
            "endtoend_id": generate_endtoend_id(execution_date, row_number),
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
                "Ausführung": payment["execution_date"],
                "Beschreibung": payment["description"],
            }
        )

    return sepa.export(validate=True), pd.DataFrame(preview_rows)


st.title("SEPA Sammelüberweisung")
st.write("Erzeuge eine XML-Datei für mehrere Überweisungen in einem Schritt.")

with st.expander("Hilfe zur Eingabedatei"):
    st.write(
        "Die Excel-Datei braucht zwei Tabellenblätter. Im Blatt `config` steht genau eine Zeile mit "
        "den Daten des Kontos, von dem überwiesen wird. Im Blatt `payments` steht pro Zeile eine "
        "einzelne Überweisung."
    )
    st.write(
        "Die Reihenfolge der beiden Blätter ist egal. Auch die Reihenfolge der Spalten ist egal, solange "
        "die benötigten Spaltennamen vorhanden sind. Zusätzliche Spalten werden einfach ignoriert."
    )
    st.write(
        "Im Zahlungsblatt werden Name, IBAN, Betrag, Ausführungsdatum und ein kurzer Verwendungszweck "
        "erwartet. Optional kannst du auch einen BIC angeben."
    )
    st.write(
        "Eine technische End-to-End-ID erzeugt die App automatisch im Hintergrund. Dazu musst du nichts "
        "eintragen."
    )
    st.write(
        "Wenn du keinen BIC angibst, wird er in der XML-Datei weggelassen. Innerhalb des SEPA-Raums ist das "
        "oft ausreichend, aber wenn dir die Bank einen BIC vorgibt, solltest du ihn mitliefern."
    )
    st.download_button(
        label="Vorlage herunterladen",
        data=TEMPLATE_PATH.read_bytes(),
        file_name=TEMPLATE_PATH.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="trf_template_download",
    )

uploaded_file = st.file_uploader("Excel-Datei hochladen", type="xlsx", key="trf_upload")

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
            file_name="sepa_ueberweisung.xml",
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
            f"Bitte prüfe insbesondere Datumswerte, Beträge und IBANs. Technischer Hinweis: {exc}"
        )
