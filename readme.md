# Data Migration Tool for Oracle PL/SQL

Flask web application that automatically generates PL/SQL code for data migration in Oracle.

## Description

This webapp allows the data migration team to upload a mapping file between source tables and target tables, and automatically generate the necessary Oracle PL/SQL code to perform the data migration. The application is designed to work in an offline environment, using a locally integrated lightweight AI model.

## Requirements

-   Python 3.7+
-   Flask
-   Pandas
-   llama-cpp-python (for local AI model integration)
-   openpyxl (for Excel support)
-   Werkzeug

## Project Structure

```
datamigration-tool/
├── app.py                 # Main application file
├── run.py                 # Startup and configuration script
├── templates/             # HTML Templates
│   ├── index.html         # Main page
│   ├── result.html        # Code generation result page
│   └── list.html          # Generated code files list
├── uploads/               # Folder for uploaded files
├── generated_code/        # Folder for generated PL/SQL code
└── models/                # Folder for AI models
    └── ggml-model-q4_0.bin  # Local AI model
```

## Installation

1.  Clone the repository:

```
git clone https://github.com/yourusername/datamigration-tool.git
cd datamigration-tool
```

2.  Create a virtual environment and activate it:

```
python -m venv venv
source venv/bin/activate  # on Windows: venv\Scripts\activate
```

3.  Install dependencies:

```
pip install -r requirements.txt
```

4.  Download the AI model using the startup script:

```
python run.py --download-model
```

## Usage

1.  Start the application:

```
python run.py
```

2.  Open your browser and navigate to `http://localhost:5000`
3.  Upload a mapping file in a supported format (CSV, JSON, or Excel)
4.  The system will generate Oracle PL/SQL code that can be downloaded or viewed directly in the interface

## Mapping File Format

The mapping file must be structured with the following columns:

### Required Columns

-   `source_table`: The name of the source table from which to extract data
-   `target_table`: The name of the destination table where data will be inserted

### Optional Columns

-   `source_columns`: Comma-separated list of columns to select from the source table
-   `target_columns`: Comma-separated list of columns in the target table (must align with source_columns)
-   `transformations`: Rules for transforming data during migration (see below)
-   `where_condition`: SQL WHERE clause to filter records from the source table
-   `related_inserts`: Instructions for inserting data into related lookup tables

### Example CSV File

csv

```csv
source_table,target_table,source_columns,target_columns,transformations,where_condition,related_inserts
CUSTOMERS_OLD,CUSTOMERS_NEW,"ID,NAME,EMAIL,REG_DATE,STATUS","ID,FULL_NAME,EMAIL,REGISTRATION_DATE,STATUS_CODE","NAME->FULL_NAME,REG_DATE->REGISTRATION_DATE,STATUS->STATUS_CODE (MAP: 'A'->1,'I'->0)","STATUS <> 'D'","KEY:migrt_key(ID):NAME"
ORDERS_OLD,ORDERS_NEW,"ORDER_ID,CUST_ID,ORDER_DATE,TOTAL_AMOUNT,PAYMENT_METHOD","ID,CUSTOMER_ID,ORDER_DATE,AMOUNT,PAYMENT_TYPE","ORDER_ID->ID,CUST_ID->CUSTOMER_ID,TOTAL_AMOUNT->AMOUNT,PAYMENT_METHOD->PAYMENT_TYPE","TOTAL_AMOUNT > 0",""
```

## Column Details

### source_columns & target_columns

These columns specify which fields to migrate and how they map between tables:

-   Must be enclosed in double quotes
-   Comma-separated list of column names
-   The order of columns in source_columns must correspond to the order in target_columns

Example:

```
"ID,NAME,EMAIL,REG_DATE,STATUS","ID,FULL_NAME,EMAIL,REGISTRATION_DATE,STATUS_CODE"
```

### transformations

Specifies how source columns map to target columns and any value transformations:

#### Simple Column Rename

Format: `SOURCE_COLUMN->TARGET_COLUMN`

Example: `NAME->FULL_NAME` means the NAME column from source will be mapped to FULL_NAME in target

#### Value Mapping Transformation

Format: `COLUMN->NEW_COLUMN (MAP: 'value1'->newvalue1,'value2'->newvalue2)`

Example: `STATUS->STATUS_CODE (MAP: 'A'->1,'I'->0)` will transform:

-   'A' values to 1
-   'I' values to 0

### where_condition

Optional SQL condition to filter source records:

-   Standard SQL WHERE clause syntax
-   No need to include the "WHERE" keyword
-   Must be enclosed in quotes if it contains commas

Example: `STATUS <> 'D'` will only migrate records where STATUS is not 'D'

### related_inserts

Instructions for inserting data into related lookup tables:

#### KEY Format

Format: `KEY:table_name(key_column):value_column`

Example: `KEY:migrt_key(ID):NAME` will:

-   Insert/update records in the `migrt_key` table
-   Using the source table's `ID` column as the key (migrt_key column)
-   Using the source table's `NAME` column as the value (migrt_value column)

## Generated Code Features

The application generates PL/SQL packages with:

-   One package per source-target table pair
-   Bulk operations (BULK COLLECT, FORALL) for performance
-   Error handling and logging
-   Transaction management (COMMIT/ROLLBACK)
-   Related table inserts with MERGE INTO statements
-   Value transformations with CASE statements

## Offline AI Functionality

The application uses a lightweight AI model (based on llama-cpp) that runs locally without internet connection. The model is used to generate customized PL/SQL code based on mapping specifications.

If the AI model is not available, the application uses a fallback code generator that produces a basic PL/SQL script.

## Requirements.txt File

```
flask==2.3.3
pandas==2.1.0
werkzeug==2.3.7
llama-cpp-python==0.2.11
openpyxl==3.1.2
requests==2.31.0
```