import streamlit as st
from sepaxml import SepaDD
import pandas as pd
import datetime
import xml.dom.minidom


# Header of Streamlit-App
st.title("SEPA XML Generator")


# Excel-File Upload
uploaded_file = st.file_uploader("Lade deine Excel-Datei hoch", type = "xlsx")


if uploaded_file is not None:

    # Import Excel_file
    #excel_file = "nutzungsentgelte.xlsx"
    
    df_config = pd.read_excel(uploaded_file, sheet_name= "config")
    df_payments = pd.read_excel(uploaded_file, sheet_name= "payments")


    # Create config_file
    config = {
        "name": df_config.loc[0, 'name'],
        "IBAN": df_config.loc[0, 'IBAN'].replace(" ", ""),
        "BIC": df_config.loc[0, 'BIC'],
        "batch": df_config.loc[0, 'batch'],         # True
        "creditor_id": df_config.loc[0, 'creditor_id'],
        "currency": df_config.loc[0, 'currency'],   # ISO 4217
    }


    # Create SEPA-transfer-object
    sepa = SepaDD(config, clean=True)


    # Add single payments -> loop over df_payments
    for index, row in df_payments.iterrows():
        payment = {
            "name": f"{row['Vorname']} {row['Name']}",
            "IBAN": row['IBAN'].replace(" ", ""),
            #"BIC": row['BIC'] if pd.notnull(row['BIC']) else "Unknown BIC",  # Fallback falls BIC fehlt
            "amount": int(round(row['amount'] * 100)),  # Betrag in Euro in Cent umrechnen
            "type": "RCUR",  # FRST, RCUR, OOFF, FNAL (wiederkehrende Lastschrift)
            "collection_date": datetime.date.today(),
            "mandate_id": row['mandate_id'],
            "mandate_date": pd.to_datetime(row['mandate_date']).date(),
            "description": row['description'],
        }
        # Zahlung zum SEPA-Transfer hinzufügen
        sepa.add_payment(payment)


    # Export SEPA-XML
    xml_content = sepa.export(validate = True)

    # Formatting XML-file
    dom = xml.dom.minidom.parseString(xml_content)
    pretty_xml_as_string = dom.toprettyxml()

    # Option for downloading XML-file
    st.download_button(
        label = "SEPA-XML-Datei herunterladen",
        data = xml_content,
        file_name= "sepa_transfer_.xml",
        mime="application/xml"
    )

    # Option zum Anzeigen der XML-Datei
    st.subheader("SEPA XML Vorschau")
    st.code(pretty_xml_as_string)



# # Save XML-file
# with open("sepa_transfer_mieten.xml", "wb") as xml_file:
#     xml_file.write(xml_content)