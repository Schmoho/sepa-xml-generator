# SEPA XML Generator

A Streamlit application that turns structured Excel workbooks into SEPA XML files for batch direct
debits (`pain.008.001.02`) and batch credit transfers (`pain.001.001.03`). It validates the workbook
shape and payment fields, previews the generated payment summary, and provides the XML for download.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run sepa.py
```

Use `dummy_lastschrift.xlsx` or `dummy_ueberweisung.xlsx` as the input template for the corresponding
workflow. The application processes uploaded workbooks in memory; do not commit filled workbooks or
generated payment files.
