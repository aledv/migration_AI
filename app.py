from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
import os
import json
import csv
import sqlite3
import pandas as pd
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Application configuration
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'csv', 'json', 'xlsx', 'xls'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['AI_MODEL_PATH'] = 'models/ggml-model-q4_0.bin'  # Path for local lightweight AI model

# Ensure necessary folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('generated_code', exist_ok=True)
os.makedirs('models', exist_ok=True)

def initialize_sample_file():
    """Initialize the sample mapping file only if it doesn't exist yet"""
    sample_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_mapping.csv')
    
    # Only create the sample file if it doesn't exist
    if not os.path.exists(sample_file_path):
        sample_content = """source_table,target_table,source_columns,target_columns,transformations,where_condition,related_inserts
CUSTOMERS_OLD,CUSTOMERS_NEW,"ID,NAME,EMAIL,REG_DATE,STATUS","ID,FULL_NAME,EMAIL,REGISTRATION_DATE,STATUS_CODE","NAME->FULL_NAME,REG_DATE->REGISTRATION_DATE,STATUS->STATUS_CODE (MAP: 'A'->1,'I'->0)","STATUS <> 'D'","KEY:migrt_key(ID):NAME"
ORDERS_OLD,ORDERS_NEW,"ORDER_ID,CUST_ID,ORDER_DATE,TOTAL_AMOUNT,PAYMENT_METHOD","ID,CUSTOMER_ID,ORDER_DATE,AMOUNT,PAYMENT_TYPE","ORDER_ID->ID,CUST_ID->CUSTOMER_ID,TOTAL_AMOUNT->AMOUNT,PAYMENT_METHOD->PAYMENT_TYPE","TOTAL_AMOUNT > 0",""
ORDER_ITEMS_OLD,ORDER_ITEMS_NEW,"ITEM_ID,ORDER_ID,PRODUCT_ID,QUANTITY,UNIT_PRICE","ID,ORDER_ID,PRODUCT_ID,QTY,PRICE","ITEM_ID->ID,QUANTITY->QTY,UNIT_PRICE->PRICE","",""
"""
        
        with open(sample_file_path, 'w') as f:
            f.write(sample_content)
        
        logger.info(f"Created sample mapping file at {sample_file_path}")

# Initialize sample file (once)
initialize_sample_file()

# AI model initialization (only if file exists)
ai_model = None
if os.path.exists(app.config['AI_MODEL_PATH']):
    try:
        import llama_cpp
        ai_model = llama_cpp.Llama(
            model_path=app.config['AI_MODEL_PATH'],
            n_ctx=2048,  # 2048 token context
            n_threads=4  # Use 4 threads for inference
        )
        logger.info(f"AI model loaded from {app.config['AI_MODEL_PATH']}")
    except Exception as e:
        logger.error(f"Error loading AI model: {e}")
else:
    logger.warning(f"AI model file not found at {app.config['AI_MODEL_PATH']}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def parse_mapping_file(file_path):
    """Parse the mapping file based on its format"""
    ext = file_path.rsplit('.', 1)[1].lower()
    
    try:
        if ext == 'csv':
            df = pd.read_csv(file_path)
            return df.to_dict(orient='records')
        elif ext == 'json':
            with open(file_path, 'r') as f:
                return json.load(f)
        elif ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path)
            return df.to_dict(orient='records')
        else:
            return None
    except Exception as e:
        logger.error(f"Error parsing file {file_path}: {e}")
        return None

def process_transformations(transformations_str):
    """Parse transformations string to extract mapping information"""
    mappings = {}
    if not transformations_str or not isinstance(transformations_str, str):
        return mappings
    
    # Log the raw transformation string for debugging
    logger.debug(f"Processing transformations: {transformations_str}")
    
    # Split by comma outside of MAP expressions
    transformations = []
    temp = ""
    map_depth = 0
    
    for char in transformations_str:
        if char == '(' and 'MAP:' in temp:
            map_depth += 1
        elif char == ')' and map_depth > 0:
            map_depth -= 1
            
        if char == ',' and map_depth == 0:
            transformations.append(temp.strip())
            temp = ""
        else:
            temp += char
    
    if temp:
        transformations.append(temp.strip())
    
    logger.debug(f"Split transformations: {transformations}")
    
    for transform in transformations:
        if '->' in transform:
            src_dest_parts = transform.split('->', 1)
            if len(src_dest_parts) != 2:
                continue
                
            src_field = src_dest_parts[0].strip()
            dest_part = src_dest_parts[1].strip()
            
            # Handle MAP: syntax
            if '(MAP:' in dest_part:
                dest_field, map_part = dest_part.split('(MAP:', 1)
                dest_field = dest_field.strip()
                
                # Remove the closing parenthesis if present
                if map_part.endswith(')'):
                    map_part = map_part[:-1].strip()
                
                # Parse value mappings
                value_maps = {}
                map_items = map_part.split(',')
                
                for item in map_items:
                    if '->' in item:
                        val_parts = item.split('->', 1)
                        if len(val_parts) == 2:
                            src_val = val_parts[0].strip().strip("'\"")
                            dest_val = val_parts[1].strip().strip("'\"")
                            value_maps[src_val] = dest_val
                
                mappings[src_field] = {
                    'dest_field': dest_field,
                    'value_maps': value_maps
                }
                
                logger.debug(f"Mapped {src_field} -> {dest_field} with values: {value_maps}")
            else:
                # Simple mapping without value transformation
                mappings[src_field] = {
                    'dest_field': dest_part
                }
    
    return mappings

def process_related_inserts(related_inserts_str):
    """Parse related insert instructions"""
    related_inserts = []
    
    if not related_inserts_str or not isinstance(related_inserts_str, str):
        return related_inserts
    
    logger.debug(f"Processing related inserts: {related_inserts_str}")
    
    # Split multiple instructions by comma
    instructions = related_inserts_str.split(',')
    
    for instruction in instructions:
        instruction = instruction.strip()
        if not instruction:
            continue
            
        # Parse KEY type instructions (KEY:target_table(key_column):value_column)
        if instruction.startswith('KEY:'):
            # Log the raw instruction for debugging
            logger.debug(f"Processing KEY instruction: {instruction}")
            
            try:
                # Extract the target table
                after_key = instruction[4:]  # Remove 'KEY:' prefix
                parts = after_key.split('(', 1)
                
                if len(parts) < 2:
                    logger.warning(f"Invalid KEY format, missing parenthesis: {instruction}")
                    continue
                    
                target_table = parts[0].strip()
                
                # Extract key column
                key_value_part = '(' + parts[1]  # Add back the opening parenthesis
                key_match = re.search(r'\(([^)]+)\)', key_value_part)
                
                if not key_match:
                    logger.warning(f"Could not find key column in: {key_value_part}")
                    continue
                    
                key_column = key_match.group(1).strip()
                
                # Extract value column
                after_parenthesis = key_value_part.split(')', 1)
                if len(after_parenthesis) < 2:
                    logger.warning(f"Invalid format, missing closing parenthesis: {key_value_part}")
                    continue
                    
                value_column = after_parenthesis[1].strip()
                if value_column.startswith(':'):
                    value_column = value_column[1:].strip()
                
                if key_column and value_column:
                    related_insert = {
                        'type': 'KEY',
                        'target_table': target_table,
                        'key_column': key_column,
                        'value_column': value_column
                    }
                    related_inserts.append(related_insert)
                    logger.debug(f"Successfully parsed related insert: {related_insert}")
            except Exception as e:
                logger.error(f"Error parsing KEY instruction '{instruction}': {e}")
    
    logger.info(f"Processed {len(related_inserts)} related inserts: {related_inserts}")
    return related_inserts

def generate_migration_code(mapping_data):
    """Generate PL/SQL migration code for Oracle based on mapping"""
    if ai_model:
        try:
            # Prepare prompt for the AI model
            prompt = "Generate PL/SQL code for Oracle to migrate data from the following tables: \n\n"
            prompt += json.dumps(mapping_data, indent=2)
            prompt += "\n\nThe code should include variable declarations, error handling, source data retrieval, necessary transformations, and insertion into destination tables. Use BULK COLLECT and FORALL where possible to improve performance."
            prompt += "\n\nFor each table mapping, create a separate package named migrt_[target_table]. Also create a main script that calls all packages."
            prompt += "\n\nFor transformations with 'MAP' expressions like 'STATUS->STATUS_CODE (MAP: 'A'->1,'I'->0)', implement CASE statements to transform values accordingly."
            prompt += "\n\nFor related_inserts instructions like 'KEY:migrt_key(ID):NAME', implement MERGE INTO statements to insert/update related lookup tables."
            
            logger.info("Requesting AI model for code generation...")
            # Execute inference with the AI model
            result = ai_model(
                prompt,
                max_tokens=2000,
                temperature=0.2,
                top_p=0.95,
                repeat_penalty=1.2,
                top_k=50
            )
            
            # Extract the generated code
            generated_code = result['choices'][0]['text']
            logger.info("Code successfully generated using AI")
            
            # Since AI might not return the expected format, we'll rely on our fallback generator
            # but we'll keep the AI output for reference
            with open(os.path.join('generated_code', f"ai_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"), 'w', encoding='utf-8') as f:
                f.write(generated_code)
                
            return generate_fallback_code(mapping_data)
        except Exception as e:
            logger.error(f"Error in AI generation: {e}")
            return generate_fallback_code(mapping_data)
    else:
        logger.info("Using fallback generator (without AI)")
        # Fallback if AI model is not available
        return generate_fallback_code(mapping_data)

def generate_fallback_code(mapping_data):
    """Generate basic PL/SQL code for Oracle when AI model is not available"""
    # Generate a script for each table combination
    scripts = []
    
    for item in mapping_data:
        source_table = item.get('source_table', 'unknown_source')
        target_table = item.get('target_table', 'unknown_target')
        source_columns = item.get('source_columns', '').split(',') if isinstance(item.get('source_columns', ''), str) else []
        target_columns = item.get('target_columns', '').split(',') if isinstance(item.get('target_columns', ''), str) else []
        where_condition = item.get('where_condition', '')
        transformations_str = item.get('transformations', '')
        related_inserts_str = item.get('related_inserts', '')
        
        # Debug logging for input values
        logger.info(f"Processing mapping: {source_table} -> {target_table}")
        logger.info(f"Transformations string: {transformations_str}")
        logger.info(f"Related inserts string: {related_inserts_str}")
        
        # Process transformations and related inserts
        transformations = process_transformations(transformations_str)
        related_inserts = process_related_inserts(related_inserts_str)
        
        logger.info(f"Processed transformations: {transformations}")
        logger.info(f"Processed related inserts: {related_inserts}")
        
        # Clean column names (remove spaces)
        source_columns = [col.strip() for col in source_columns if col.strip()]
        target_columns = [col.strip() for col in target_columns if col.strip()]
        
        # If no columns are specified, use generic placeholders
        if not source_columns:
            source_columns = ["ID", "COLUMN1", "COLUMN2", "CREATED_DATE"]
        if not target_columns and source_columns:
            # Map source columns to target columns based on transformations
            target_columns = []
            for src_col in source_columns:
                if src_col in transformations and 'dest_field' in transformations[src_col]:
                    target_columns.append(transformations[src_col]['dest_field'])
                else:
                    target_columns.append(src_col)
        
        # Create package name based on destination table
        package_name = f"migrt_{target_table.lower()}"
        
        # Start building the code
        code = f"""
SET SERVEROUTPUT ON;

-- Data migration package for {source_table} to {target_table}
CREATE OR REPLACE PACKAGE {package_name} AS
  -- Main migration procedure
  PROCEDURE migrate_data;
END {package_name};
/

CREATE OR REPLACE PACKAGE BODY {package_name} AS
  -- Variables declaration
  v_error_message VARCHAR2(4000);
  v_count NUMBER;
  
  -- Migration procedure
  PROCEDURE migrate_data IS
    -- Type definitions for bulk collect
    TYPE t_source_rec IS RECORD (
"""
        # Record definition with columns
        for i, col in enumerate(source_columns):
            code += f"      {col.strip()} "
            # Generic data type based on column name
            if "ID" in col.upper() or col.upper().endswith("_ID"):
                code += "NUMBER"
            elif "DATE" in col.upper() or "TIME" in col.upper():
                code += "DATE"
            elif "AMOUNT" in col.upper() or "PRICE" in col.upper() or "COST" in col.upper():
                code += "NUMBER"
            else:
                code += "VARCHAR2(4000)"
                
            if i < len(source_columns) - 1:
                code += ","
            code += "\n"
            
        code += """    );
    TYPE t_source_tab IS TABLE OF t_source_rec;
    v_source_data t_source_tab;
  BEGIN
    -- Display start message
    DBMS_OUTPUT.PUT_LINE('Starting migration from """
        
        code += f"{source_table} to {target_table}: ' || TO_CHAR(SYSDATE, 'DD-MON-YYYY HH24:MI:SS'));\n\n"
        code += f"    -- Retrieve data from source table\n    SELECT \n"
        
        # SELECT source columns
        for i, col in enumerate(source_columns):
            code += f"      {col.strip()}"
            if i < len(source_columns) - 1:
                code += ","
            code += "\n"
            
        code += f"""    BULK COLLECT INTO v_source_data
    FROM {source_table}"""
        
        # Add WHERE condition if present
        if where_condition:
            code += f"\n    WHERE {where_condition}"
        
        code += """    ;
    
    -- Number of records found
    v_count := v_source_data.COUNT;
    DBMS_OUTPUT.PUT_LINE('Found ' || v_count || ' records to migrate.');
    
    -- If records found, process them
    IF v_count > 0 THEN
"""
        
        # Explicitly check for related inserts and add them if present
        if related_inserts and len(related_inserts) > 0:
            logger.info(f"Adding related inserts code for {len(related_inserts)} items")
            
            # Process related inserts first - one at a time in a loop
            code += """      -- First, process related inserts for each record
      FOR i IN 1..v_source_data.COUNT LOOP
"""
            
            # Add code for each related insert type
            for related_insert in related_inserts:
                if related_insert['type'] == 'KEY':
                    target_table_rel = related_insert['target_table']
                    key_column = related_insert['key_column']
                    value_column = related_insert['value_column']
                    
                    logger.info(f"Adding KEY related insert for {target_table_rel} with key={key_column}, value={value_column}")
                    
                    code += f"""        -- Insert/update record in {target_table_rel} lookup table
        BEGIN
          MERGE INTO {target_table_rel} t
          USING (SELECT v_source_data(i).{key_column} as key_val, 
                       v_source_data(i).{value_column} as value_val 
                 FROM dual) s
          ON (t.migrt_key = s.key_val)
          WHEN MATCHED THEN
            UPDATE SET t.migrt_value = s.value_val
          WHEN NOT MATCHED THEN
            INSERT (migrt_key, migrt_value)
            VALUES (s.key_val, s.value_val);
          
          DBMS_OUTPUT.PUT_LINE('Processed lookup record for key: ' || v_source_data(i).{key_column});
        EXCEPTION
          WHEN OTHERS THEN
            v_error_message := SQLERRM;
            DBMS_OUTPUT.PUT_LINE('Error during related insert to {target_table_rel}: ' || v_error_message);
            -- Continue with the migration process
        END;
"""
            
            # Close the loop for related inserts
            code += """      END LOOP;
      
      -- Commit the related inserts
      COMMIT;
      DBMS_OUTPUT.PUT_LINE('Related records committed successfully.');
      
"""
        
        # Now add the main insert code (this happens after all related inserts)
        code += f"""      -- Now, insert into the main target table
      FORALL i IN 1..v_source_data.COUNT
        INSERT INTO {target_table} (
"""
        
        # Destination columns for INSERT
        for i, col in enumerate(target_columns):
            code += f"          {col.strip()}"
            if i < len(target_columns) - 1:
                code += ","
            code += "\n"
            
        code += "        ) VALUES (\n"
        
        # Values for INSERT with transformations
        for i, src_col in enumerate(source_columns):
            src_col = src_col.strip()
            
            # Make sure we don't go out of bounds with target_columns
            if i < len(target_columns):
                tgt_col = target_columns[i].strip()
                
                code += "          "
                
                # Check if this column has a value mapping transformation
                if src_col in transformations and 'value_maps' in transformations[src_col]:
                    # Generate CASE WHEN for value transformation
                    code += f"CASE v_source_data(i).{src_col}\n"
                    for src_val, dest_val in transformations[src_col]['value_maps'].items():
                        code += f"            WHEN '{src_val}' THEN {dest_val}\n"
                    code += f"            ELSE v_source_data(i).{src_col}\n          END"
                else:
                    # Use the value directly
                    code += f"v_source_data(i).{src_col}"
                
                if i < len(target_columns) - 1:
                    code += ","
                code += "\n"
            
        code += """        );
        
      DBMS_OUTPUT.PUT_LINE('Inserted ' || SQL%ROWCOUNT || ' records into main table.');
      COMMIT;
      DBMS_OUTPUT.PUT_LINE('Main table data committed successfully.');
    ELSE
      DBMS_OUTPUT.PUT_LINE('No records to migrate.');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('Migration completed: ' || TO_CHAR(SYSDATE, 'DD-MON-YYYY HH24:MI:SS'));
  EXCEPTION
    WHEN OTHERS THEN
      v_error_message := SQLERRM;
      DBMS_OUTPUT.PUT_LINE('Error during migration: ' || v_error_message);
      ROLLBACK;
      RAISE;
  END migrate_data;
END """
        
        code += f"{package_name};\n/\n\n"
        code += f"""-- Execute migration
BEGIN
  {package_name}.migrate_data;
END;
/
"""
        # Add this script to our collection
        scripts.append({
            'filename': f"{package_name}.sql",
            'code': code,
            'source_table': source_table,
            'target_table': target_table
        })
    
    # Create main controller script that calls all individual packages
    main_script = """
SET SERVEROUTPUT ON;

-- Main migration controller
BEGIN
  DBMS_OUTPUT.PUT_LINE('=== DATA MIGRATION START: ' || TO_CHAR(SYSDATE, 'DD-MON-YYYY HH24:MI:SS') || ' ===');
  DBMS_OUTPUT.PUT_LINE('');

"""
    
    # Add calls to each package
    for i, script in enumerate(scripts):
        package_name = f"migrt_{script['target_table'].lower()}"
        main_script += f"""  -- Migration {i+1}: {script['source_table']} to {script['target_table']}
  BEGIN
    {package_name}.migrate_data;
    DBMS_OUTPUT.PUT_LINE('');
  EXCEPTION
    WHEN OTHERS THEN
      DBMS_OUTPUT.PUT_LINE('Error in {package_name}: ' || SQLERRM);
      DBMS_OUTPUT.PUT_LINE('');
  END;
"""
        if i < len(scripts) - 1:
            main_script += "\n"
    
    main_script += """
  DBMS_OUTPUT.PUT_LINE('=== DATA MIGRATION END: ' || TO_CHAR(SYSDATE, 'DD-MON-YYYY HH24:MI:SS') || ' ===');
END;
/
"""
    
    # Add the main script to our collection
    scripts.append({
        'filename': "migrate_all.sql",
        'code': main_script,
        'source_table': "ALL",
        'target_table': "ALL"
    })
    
    # Save all scripts to files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_files = []
    
    # Create index file for all generated files
    index_data = []
    
    for script in scripts:
        # Use a format for filenames that explicitly includes source and target tables
        if script['source_table'] == "ALL" and script['target_table'] == "ALL":
            filename = f"{timestamp}_migrate_all.sql"
        else:
            # Sanitize table names for filenames
            source_name = re.sub(r'[^\w]', '_', script['source_table'])
            target_name = re.sub(r'[^\w]', '_', script['target_table'])
            filename = f"{timestamp}_{source_name}_to_{target_name}.sql"
        
        file_path = os.path.join('generated_code', filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(script['code'])
        
        file_info = {
            'filename': filename,
            'source_table': script['source_table'],
            'target_table': script['target_table'],
            'timestamp': timestamp
        }
        
        saved_files.append(file_info)
        index_data.append(file_info)
    
    # Save index data to a JSON file
    index_path = os.path.join('generated_code', 'file_index.json')
    
    # Load existing index if it exists
    existing_index = []
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                existing_index = json.load(f)
        except Exception as e:
            logger.warning(f"Error reading existing index: {e}")
    
    # Update index with new files
    updated_index = existing_index + index_data
    
    # Save updated index
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(updated_index, f, indent=2)
    
    # Return information about the generated files
    return saved_files

@app.route('/')
def index():
    logger.info("Homepage access")
    
    # Verifica se il file esiste già e quando è stato modificato l'ultima volta
    sample_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_mapping.csv')
    if os.path.exists(sample_file_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(sample_file_path))
        logger.info(f"Sample file exists, last modified: {mod_time}")
    else:
        logger.info("Sample file does not exist, creating it now")
        initialize_sample_file()
    
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    logger.info(f"Call to upload_file with method: {request.method}")
    logger.info(f"Form keys: {list(request.form.keys())}")
    logger.info(f"Files keys: {list(request.files.keys())}")
    
    if 'file' not in request.files:
        logger.warning("No file in request")
        return redirect(url_for('index'))
    
    file = request.files['file']
    
    if file.filename == '':
        logger.warning("Empty filename")
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        logger.info(f"Valid file received: {file.filename}")
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        logger.info(f"File saved to: {file_path}")
        
        # Parse mapping file
        mapping_data = parse_mapping_file(file_path)
        
        if mapping_data:
            logger.info(f"Mapping parsed successfully: {len(mapping_data)} tables found")
            
            # Generate migration code - now returns a list of files
            generated_files = generate_migration_code(mapping_data)
            
            logger.info(f"Generated {len(generated_files)} script files")
            
            # Redirect to the list of generated files
            return render_template('generated_files.html', 
                                  files=generated_files,
                                  mapping_data=mapping_data)
        else:
            logger.error("Error parsing mapping file")
            return "Error parsing mapping file", 400
    
    logger.warning(f"Unsupported file type: {file.filename}")
    return "Unsupported file type", 400

@app.route('/download/<filename>')
def download_code(filename):
    logger.info(f"Download requested for: {filename}")
    path = os.path.join('generated_code', filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            code = f.read()
        return jsonify({'code': code, 'filename': filename})
    logger.warning(f"File not found: {path}")
    return "File not found", 404

@app.route('/list_generated')
def list_generated():
    logger.info("Access to generated files list")
    
    # Load file index if exists
    index_path = os.path.join('generated_code', 'file_index.json')
    file_index = {}
    
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
                for item in index_data:
                    if 'filename' in item:
                        file_index[item['filename']] = item
            logger.info(f"Loaded file index with {len(file_index)} entries")
        except Exception as e:
            logger.error(f"Error reading file index: {e}")
    
    # Collect all SQL files
    files = []
    for filename in os.listdir('generated_code'):
        if filename.endswith('.sql'):
            file_path = os.path.join('generated_code', filename)
            
            # Get file info either from index or by parsing filename
            if filename in file_index:
                # Use data from index
                source_table = file_index[filename].get('source_table', 'Unknown')
                target_table = file_index[filename].get('target_table', 'Unknown')
            else:
                # Parse from filename
                source_table = "Unknown"
                target_table = "Unknown"
                
                # Extract from filename pattern: timestamp_source_to_target.sql
                if "_to_" in filename:
                    parts = filename.split('_to_')
                    if len(parts) == 2:
                        # First part should be timestamp_source
                        source_parts = parts[0].split('_', 1)
                        if len(source_parts) > 1:
                            source_table = source_parts[1]
                        
                        # Second part should be target.sql
                        target_parts = parts[1].split('.')
                        if len(target_parts) > 0:
                            target_table = target_parts[0]
                elif "migrate_all" in filename:
                    source_table = "ALL"
                    target_table = "ALL"
            
            files.append({
                'filename': filename,
                'date': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),
                'source_table': source_table,
                'target_table': target_table
            })
    
    # Sort by date (newest first)
    files.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('list.html', files=files)

@app.route('/debug_related_inserts')
def debug_related_inserts():
    test_string = "KEY:migrt_key(ID):NAME"
    
    try:
        # Log dettagliato del processo di parsing
        logger.info(f"Testing related inserts parsing with: {test_string}")
        
        # Esecuzione del parser
        result = process_related_inserts(test_string)
        
        # Verifica del risultato
        if result and len(result) > 0:
            logger.info(f"Successfully parsed: {result}")
        else:
            logger.warning(f"Parser returned empty result for: {test_string}")
        
        # Analisi passo per passo
        parts_analysis = {}
        
        # Test parsing manuale
        if test_string.startswith("KEY:"):
            parts_analysis["step1"] = "String starts with KEY:"
            
            after_key = test_string[4:]
            parts_analysis["after_key"] = after_key
            
            # Split by opening parenthesis
            target_parts = after_key.split('(', 1)
            parts_analysis["target_parts"] = target_parts
            
            if len(target_parts) >= 2:
                target_table = target_parts[0].strip()
                parts_analysis["target_table"] = target_table
                
                key_value_part = '(' + target_parts[1]
                parts_analysis["key_value_part"] = key_value_part
                
                # Extract key column using regex
                key_match = re.search(r'\(([^)]+)\)', key_value_part)
                parts_analysis["key_match"] = str(key_match)
                
                if key_match:
                    key_column = key_match.group(1).strip()
                    parts_analysis["key_column"] = key_column
                    
                    # Extract value column
                    value_column_part = key_value_part.split(')', 1)
                    parts_analysis["value_column_part"] = value_column_part
                    
                    if len(value_column_part) >= 2:
                        value_column = value_column_part[1].strip()
                        if value_column.startswith(':'):
                            value_column = value_column[1:].strip()
                        parts_analysis["value_column"] = value_column
        
        return jsonify({
            'input': test_string,
            'output': result,
            'parts_analysis': parts_analysis
        })
    except Exception as e:
        logger.error(f"Error in debug_related_inserts: {e}")
        return jsonify({
            'input': test_string,
            'output': [],
            'error': str(e)
        })

@app.route('/debug_files')
def debug_files():
    # Elenco dei file nella directory generated_code
    files = []
    for filename in os.listdir('generated_code'):
        file_path = os.path.join('generated_code', filename)
        file_info = {
            'filename': filename,
            'size': os.path.getsize(file_path),
            'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Se è un file SQL, aggiungi prime righe di contenuto
        if filename.endswith('.sql'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_info['first_lines'] = f.read(200)  # Prime 200 caratteri
            except Exception as e:
                file_info['error'] = str(e)
        
        files.append(file_info)
    
    return jsonify({
        'files': files
    })

@app.route('/sample_mapping.csv')
def serve_sample_mapping():
    """Serve the sample mapping file from a dedicated location"""
    sample_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_mapping.csv')
    
    if not os.path.exists(sample_file_path):
        initialize_sample_file()
        
    return send_from_directory(app.config['UPLOAD_FOLDER'], 'sample_mapping.csv', as_attachment=True)

# Serve static files from uploads folder
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Serve static files from generated_code folder
@app.route('/generated_code/<filename>')
def generated_file(filename):
    return send_from_directory('generated_code', filename)

# Diagnostic route to check application status
@app.route('/status')
def app_status():
    status = {
        "app": "Data Migration Tool",
        "status": "running",
        "ai_model": "loaded" if ai_model else "not_loaded",
        "uploads_dir": os.path.exists(app.config['UPLOAD_FOLDER']),
        "generated_code_dir": os.path.exists('generated_code'),
        "models_dir": os.path.exists('models'),
        "routes": [str(rule) for rule in app.url_map.iter_rules()]
    }
    return jsonify(status)

if __name__ == '__main__':
    # Print registered routes
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.methods} - {rule}")
    
    app.run(debug=True, host='0.0.0.0', port=5001)