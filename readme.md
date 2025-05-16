# Data Migration Tool per Oracle PL/SQL

Applicazione Flask che genera automaticamente codice PL/SQL per la migrazione di dati in Oracle.

## Descrizione
Questa webapp consente al team di datamigration di caricare un file di mapping tra tabelle sorgenti e tabelle destinazione, e generare automaticamente il codice PL/SQL per Oracle necessario per eseguire la migrazione dei dati. L'applicazione è progettata per funzionare in un ambiente senza connessione internet, utilizzando un modello AI leggero integrato localmente.

## Requisiti
- Python 3.7+
- Flask
- Pandas
- llama-cpp-python (per l'integrazione del modello AI locale)
- openpyxl (per supporto Excel)
- Werkzeug

## Struttura del progetto
```
datamigration-tool/
├── app.py                 # File principale dell'applicazione
├── run.py                 # Script di avvio e configurazione
├── templates/             # Template HTML
│   ├── index.html         # Pagina principale
│   ├── result.html        # Pagina del risultato della generazione
│   └── list.html          # Elenco dei file di codice generati
├── uploads/               # Cartella per i file caricati
├── generated_code/        # Cartella per il codice PL/SQL generato
└── models/                # Cartella per i modelli AI
    └── ggml-model-q4_0.bin  # Modello AI locale
```

## Installazione
1. Clona il repository:
```
git clone https://github.com/yourusername/datamigration-tool.git
cd datamigration-tool
```

2. Crea un ambiente virtuale e attivalo:
```
python -m venv venv
source venv/bin/activate  # su Windows: venv\Scripts\activate
```

3. Installa le dipendenze:
```
pip install -r requirements.txt
```

4. Scarica il modello AI utilizzando lo script di avvio:
```
python run.py --download-model
```

## Utilizzo
1. Avvia l'applicazione:
```
python run.py
```

2. Apri il browser e naviga all'indirizzo `http://localhost:5000`

3. Carica un file di mapping nel formato supportato (CSV, JSON o Excel)

4. Il sistema genererà il codice PL/SQL per Oracle che può essere scaricato o visualizzato direttamente nell'interfaccia

## Formato del file di mapping
Il file di mapping deve contenere almeno le seguenti colonne:
- `source_table`: Nome della tabella sorgente
- `target_table`: Nome della tabella destinazione

Colonne opzionali:
- `source_columns`: Elenco delle colonne della tabella sorgente
- `target_columns`: Elenco delle colonne della tabella destinazione
- `transformations`: Regole di trasformazione dei dati
- `where_condition`: Condizione WHERE per filtrare i dati sorgente

### Esempio di file CSV:
```csv
source_table,target_table,source_columns,target_columns,transformations,where_condition
CUSTOMERS_OLD,CUSTOMERS_NEW,"ID,NAME,EMAIL,REG_DATE,STATUS","ID,FULL_NAME,EMAIL,REGISTRATION_DATE,STATUS_CODE","NAME->FULL_NAME,REG_DATE->REGISTRATION_DATE,STATUS->STATUS_CODE (MAP: 'A'->1,'I'->0)","STATUS <> 'D'"
ORDERS_OLD,ORDERS_NEW,"ORDER_ID,CUST_ID,ORDER_DATE,TOTAL_AMOUNT,PAYMENT_METHOD","ID,CUSTOMER_ID,ORDER_DATE,AMOUNT,PAYMENT_TYPE","ORDER_ID->ID,CUST_ID->CUSTOMER_ID,TOTAL_AMOUNT->AMOUNT,PAYMENT_METHOD->PAYMENT_TYPE","TOTAL_AMOUNT > 0"
```

## Funzionamento dell'AI offline
L'applicazione utilizza un modello AI leggero (basato su llama-cpp) che viene eseguito localmente senza bisogno di connessione internet. Il modello viene utilizzato per generare codice PL/SQL personalizzato in base alle specifiche di mapping.

Se il modello AI non è disponibile, l'applicazione utilizza un generatore di codice di fallback che produce uno script PL/SQL di base.

## File requirements.txt
```
flask==2.3.3
pandas==2.1.0
werkzeug==2.3.7
llama-cpp-python==0.2.11
openpyxl==3.1.2
requests==2.31.0
```
