# Server Stats

Dashboard in italiano, interamente in Docker, senza dipendenze frontend o servizi esterni. CPU totale e per core, load average, RAM e swap, spazio dei filesystem, rete per interfaccia, lettura/scrittura e occupazione dei dischi fisici, temperature hwmon e watt dei sensori hardware o dei package CPU RAPL. Campionamento e durata dei grafici configurabili (default: ogni secondo, ultimi 10 minuti); lo storico in memoria si azzera al riavvio.

## Prima configurazione

Richiede un host Linux con Docker Engine e Docker Compose, e Python 3 per generare le credenziali. Non richiede librerie Python aggiuntive. Il container legge `/proc`, `/sys` e i filesystem dell’host in sola lettura; non usa il socket Docker.

```sh
cp .env.example .env
# Modificare nome, colori, porta e altre impostazioni in .env.
python3 credentials.py --username admin
docker compose up -d --build
```

Configurare il proprio dominio e il reverse proxy HTTPS usando `Caddyfile.example`, quindi aprire `https://stats.example.com`. Il login richiede HTTPS perché il cookie di sessione è Secure. La porta 8091 è l’upstream HTTP del proxy; l’esempio la espone su `127.0.0.1`. Se il proxy è su un altro host o in una rete Docker bridge, impostare `BIND_ADDRESS` su un indirizzo raggiungibile dal proxy.

Non copiare nuovamente `.env.example` sopra una configurazione esistente: sovrascriverebbe impostazioni e credenziali.

## Personalizzazione

Tutte le impostazioni iniziali sono in `.env`, caricato da Docker Compose. Dopo una modifica eseguire `docker compose up -d` per ricreare il container con i nuovi valori. I valori omessi usano i default neutri di `config.py`.

| Variabile | Default | Funzione |
| --- | --- | --- |
| `STATS_NAME` | `Server` | Nome in intestazione, login e titolo browser |
| `STATS_LABEL` | `Stats` | Etichetta accanto al nome e nel titolo |
| `STATS_HEADING` | `Il server, a colpo d’occhio.` | Titolo della dashboard |
| `STATS_ACCENT` | `#63e6b4` | Colore principale, barre e grafici |
| `STATS_SECONDARY` | `#729dff` | Colore invio/scrittura nei grafici |
| `STATS_SAMPLE_SECONDS` | `1` | Intervallo di raccolta e aggiornamento, da 0,25 a 10 secondi |
| `STATS_HISTORY_SECONDS` | `600` | Durata dello storico in memoria, da 60 a 3600 secondi |
| `STATS_TIMEZONE` | `Europe/Rome` | Fuso IANA per giorni e mesi del conteggio energetico |
| `STATS_INITIAL_PRICE` | `0.30` | Tariffa €/kWh iniziale, da 0 a 100, solo per database nuovi |
| `STATS_PORT` | `8091` | Porta HTTP pubblicata da Compose |
| `BIND_ADDRESS` | `0.0.0.0` | Indirizzo di ascolto; l’esempio usa `127.0.0.1` |
| `STATS_USERNAME` | `admin` | Nome utente del login |
| `STATS_PASSWORD_HASH` | vuoto | Hash generato con `credentials.py`, obbligatorio |

Per testi e colori usare apici singoli, come in `.env.example`. Per esempio `STATS_NAME='La mia infrastruttura'`. I nomi accettano da 1 a 200 caratteri; i colori devono essere esadecimali `#RRGGBB`. Le impostazioni non valide impediscono l’avvio con un errore. Le pagine ricevono soltanto valori pubblici, con escaping HTML; l’hash non viene esposto. La valuta rimane EUR e l’interfaccia è in italiano.

Il fuso va scelto prima di iniziare il conteggio: cambiarlo non converte lo storico già aggregato. La tariffa iniziale non sovrascrive quella di un database esistente; per cambiarla usare **Salva tariffa**.

Per esecuzioni fuori da Docker si possono impostare anche `HOST_PROC`, `HOST_SYS`, `HOST_ROOT` ed `ENERGY_DB`; lo script server legge le variabili dell’ambiente, non carica autonomamente `.env`.

## Struttura e pubblicazione su GitHub

- `config.py`: impostazioni e validazione.
- `metrics.py`: raccolta delle metriche Linux, senza dipendenze HTTP.
- `server.py`: API, autenticazione delle richieste, rendering e ciclo di raccolta.
- `auth.py` e `credentials.py`: sessioni e gestione credenziali.
- `energy_store.py`: persistenza energetica SQLite.
- `static/`: interfaccia, grafici e proiezioni energetiche.

Il repository contiene esempi neutri: ogni installazione sceglie il proprio nome e dominio. `.gitignore` esclude `.env`, credenziali locali, database e cache; `.dockerignore` ammette soltanto codice e asset necessari. Pubblicare la cartella di questo progetto come repository dedicato, non la directory home che la contiene. Prima del push controllare i file staged con `git diff --cached --name-only`; se segreti erano già tracciati, `.gitignore` da solo non li rimuove dalla cronologia.

La dashboard necessita del backend Linux e non è distribuibile come sito statico su GitHub Pages. GitHub ospita il codice; Docker e il proxy HTTPS eseguono il servizio sul proprio server.

## Verifica

```sh
python3 -m unittest discover -v
node --check static/app.js
node --check static/energy.js
node --check static/login.js
docker compose ps
docker compose logs --tail=50
curl http://127.0.0.1:8091/health
```

La CI GitHub Actions esegue i test Python e controlla la sintassi JavaScript e la build Docker. `/api/stats` richiede una sessione autenticata.

## Caddy e dominio

Aggiungere il blocco di `Caddyfile.example` alla configurazione del proprio Caddy. Il dominio deve avere DNS verso il server e Caddy deve poter ricevere le connessioni sulle porte HTTP/HTTPS. Se Caddy gira sull'host o in un container con rete host, `127.0.0.1:8091` è l'upstream corretto. Se Caddy gira in una rete Docker bridge, usare l'IP dell'host raggiungibile da quel container oppure una rete condivisa e `stats:80`.

Validare e ricaricare la configurazione con il metodo previsto dalla propria installazione di Caddy. Il file incluso è un esempio pronto da integrare, non sostituisce le configurazioni degli altri siti. Per limitare l'accesso al solo Caddy sullo stesso host impostare `BIND_ADDRESS=127.0.0.1`. Per un dominio privato si può aggiungere autenticazione nel blocco Caddy.

## Fonti e limiti

Il container legge `/proc`, `/sys` e il filesystem host tramite mount in sola lettura; non usa il socket Docker, né modalità privileged. I contatori rete provengono da `/proc/1/net/dev` per misurare le interfacce dell'host anziché quelle del container. RAM e CPU sono quelle del server, non i limiti del container. Il root host è montato per misurare tutti i filesystem, inclusi i mount aggiunti successivamente tramite propagazione rslave.

L'I/O aggregato somma i dispositivi fisici, escludendo partizioni, loop e device mapper per evitare il doppio conteggio. Il riepilogo rete e il suo grafico sommano solo le interfacce fisiche; la tabella include anche le interfacce virtuali. Lo spazio usato percentuale considera lo spazio disponibile agli utenti, escludendo i blocchi riservati. Il primo campione di contatori è zero perché manca ancora un intervallo di confronto.

I watt RAPL sono derivati dalla differenza del contatore `energy_uj`, gestendo il wrap del contatore: riguardano il package CPU e **non il consumo totale del server**. Le zone figlie non vengono sommate per evitare doppio conteggio. Sensori mancanti o non leggibili appaiono come non disponibili; non si stimano watt dal TDP. Per il consumo alla presa serve un misuratore esterno. Riferimento: https://www.kernel.org/doc/html/latest/power/powercap/powercap.html

## Stima del costo elettrico

La sezione permette di impostare il prezzo in €/kWh (valore iniziale modificabile: 0,30) e una potenza totale stimata opzionale in watt. La tariffa si salva sul server con il pulsante Salva tariffa; la potenza manuale resta nel localStorage del browser. Senza potenza manuale si usa la media delle misure dei package CPU disponibili nell'ultimo minuto: il risultato è il costo della sola CPU. I sensori generici hwmon non vengono sommati ai package per evitare doppio conteggio. In assenza di contatori CPU e potenza manuale il costo non è disponibile.

Le proiezioni oraria, giornaliera e mensile (30 giorni) assumono potenza costante: `costo = watt / 1000 * ore * prezzo_kWh`. Non costituiscono uno storico della bolletta e non includono costi fissi. Per stimare tutto il server inserire la potenza totale, preferibilmente misurata alla presa.

## Login nativo

La pagina e tutte le API delle statistiche richiedono nome utente e password. Il login è disponibile su `https://stats.example.com/login`. Usare HTTPS: il cookie di sessione è Secure, HttpOnly, SameSite=Strict e scade dopo 12 ore. Le sessioni vengono invalidate al riavvio e al logout. Il backend limita a 20 richieste di login al minuto. Solo la pagina di login, i suoi asset (incluso il tema pubblico) e il controllo `/health` sono pubblici.

`.env` contiene il nome utente e l'hash PBKDF2-SHA256 della password (600.000 iterazioni), ed è escluso dall'immagine Docker e da Git. Per impostare o cambiare le credenziali:

```sh
python3 credentials.py --username admin
docker compose up -d
```

Lo script chiede e conferma la password senza mostrarla, preserva le altre impostazioni di `.env` ed elimina il file delle credenziali iniziali. Per una nuova installazione copiare `.env.example` in `.env`, eseguire lo script, poi `docker compose up -d --build`. I test dell'autenticazione si eseguono con `python3 test_dashboard.py` e usano credenziali di prova separate.


## Energia misurata e costo maturato

Il backend somma le differenze del contatore hardware RAPL `energy_uj` dei package CPU, senza arrotondare i watt e senza includere due volte le zone figlie. `1 kWh = 3.600.000.000.000 microjoule`. Il costo di ogni nuovo intervallo è l'energia effettivamente rilevata moltiplicata per la tariffa salvata (inizialmente 0,30 €/kWh). Le modifiche alla tariffa si applicano ai nuovi campioni: non ricalcolano i costi già maturati. Per usare un nuovo prezzo occorre premere **Salva tariffa**, non basta modificare il campo.

La pagina mostra energia e costo cumulativi di oggi, del mese civile in corso e dall'attivazione del conteggio, con ultimi 31 giorni registrati e copertura delle misure. Il fuso è quello configurato in `STATS_TIMEZONE` (default Europe/Rome), incluse le variazioni dell’ora legale. Un intervallo che attraversa mezzanotte viene ripartito proporzionalmente tra i due giorni.

I dati sono conservati in SQLite nel volume Docker `stats-data`, montato su `/data`: il conteggio continua anche senza browser aperti e sopravvive a riavvio, ricostruzione e ricreazione del container. Non eliminare il volume con `docker compose down -v` se vuoi conservare lo storico. Viene salvato ogni campione in una transazione; non occorre un database esterno.

Il conteggio parte dall'installazione di questa funzione: i consumi precedenti non sono ricostruibili. Se il monitor è fermo, il sensore non è leggibile o il tempo tra letture supera 30 secondi, il periodo è registrato come non misurato ed escluso dall'energia e dal costo. Al riavvio si riparte da un nuovo contatore di riferimento; non si attribuiscono consumi ipotetici al periodo di arresto. Il costo riguarda solo l'energia CPU RAPL, non l'intero server né la bolletta (che può includere quote fisse). La potenza totale inserita manualmente continua a essere usata soltanto per le proiezioni.

Verifica: `python3 -m unittest test_energy test_dashboard`. I test energetici coprono conversione, wrap del contatore, cambio tariffa senza ricalcolo retroattivo, persistenza, interruzioni e passaggi di giorno/mese e ora legale.
