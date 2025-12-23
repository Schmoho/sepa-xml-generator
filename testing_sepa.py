from sepaxml import SepaDD
import pandas as pd
import datetime
import xml.dom.minidom



# Filepath
df_filepath = "../sepa_generator/20240923_Nutzungsentgelte.xlsx"

# Import Excel
df = pd.read_excel(df_filepath, sheet_name = "payments")
print(df)


# Column selection
df_red = df.iloc[:, 1:7]


# Calculate amount column.
df['amount_100'] = (df['amount'] * 100)
df['amount_int'] = (df['amount'] * 100).astype(int)
df['amount_int_round'] = (df['amount'] * 100).round().astype(int)
df.iloc[:, [1,2,3,4,6,7,16]]
57233.0.astype(int)
