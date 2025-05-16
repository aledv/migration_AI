import os
import argparse
import logging
from flask import Flask
from werkzeug.serving import run_simple

def download_model(model_url, model_path):
    """
    Scarica il modello AI se non è già presente.
    Questa funzione è utile per l'installazione iniziale.
    """
    if os.path.exists(model_path):
        print(f"Il modello è già presente in: {model_path}")
        return
    
    try:
        import requests
        print(f"Scaricamento del modello da: {model_url}")
        print("Questo potrebbe richiedere alcuni minuti...")
        
        response = requests.get(model_url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024  # 1 Kibibyte
        downloaded = 0
        
        # Assicurati che la directory esista
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        
        with open(model_path, 'wb') as f:
            for data in response.iter_content(block_size):
                downloaded += len(data)
                f.write(data)
                done = int(50 * downloaded / total_size)
                print(f"\r[{'=' * done}{' ' * (50 - done)}] {downloaded}/{total_size} bytes", end='')
        
        print("\nDownload completato!")
    except Exception as e:
        print(f"Errore durante il download del modello: {e}")
        print("Per favore, scarica manualmente il modello e posizionalo in:", model_path)

def setup_app():
    """
    Configura l'ambiente dell'applicazione.
    Crea le cartelle necessarie.
    """
    # Crea le directory necessarie
    for directory in ['uploads', 'generated_code', 'models', 'templates']:
        os.makedirs(directory, exist_ok=True)
    
    # Verifica se i template esistono già
    template_files = {
        'templates/index.html': 'Template pagina principale',
        'templates/result.html': 'Template pagina risultato',
        'templates/list.html': 'Template elenco codice generato'
    }
    
    for template_path, description in template_files.items():
        if not os.path.exists(template_path):
            print(f"ATTENZIONE: {description} non trovato in: {template_path}")
            print("Assicurati di copiare tutti i file template nella cartella 'templates/'")

def main():
    parser = argparse.ArgumentParser(description='Data Migration Tool - Avvio server Flask')
    parser.add_argument('-p', '--port', type=int, default=5001, help='Porta su cui avviare il server (default: 5001)')
    parser.add_argument('-d', '--debug', action='store_true', help='Avvia in modalità debug')
    parser.add_argument('--download-model', action='store_true', help='Scarica il modello AI')
    parser.add_argument('--model-url', type=str, 
                        default='https://huggingface.co/TheBloke/Llama-2-7B-GGUF/resolve/main/llama-2-7b.Q4_0.gguf',
                        help='URL da cui scaricare il modello AI')
    
    args = parser.parse_args()
    
    # Configurazione del logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configura le directory e verifica i template
    setup_app()
    
    # Percorso del modello AI
    model_path = os.path.join('models', 'ggml-model-q4_0.bin')
    
    # Scarica il modello se richiesto
    if args.download_model:
        download_model(args.model_url, model_path)
    
    # Verifica la presenza del modello
    if not os.path.exists(model_path):
        print(f"AVVISO: Il modello AI non è presente in {model_path}")
        print("L'applicazione funzionerà in modalità fallback senza generazione AI.")
        print(f"Per scaricare il modello, esegui: python {__file__} --download-model")
    
    # Avvio dell'app Flask
    from app import app
    
    print(f"\nData Migration Tool - Avvio del server su http://127.0.0.1:{args.port}")
    print("Premi CTRL+C per terminare il server\n")
    
    try:
        if args.debug:
            app.run(host='0.0.0.0', port=args.port, debug=True)
        else:
            run_simple('0.0.0.0', args.port, app, use_reloader=False)
    except KeyboardInterrupt:
        print("\nServer terminato")

if __name__ == '__main__':
    main()
