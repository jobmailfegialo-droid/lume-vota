# Mangiù · sito pubblico

Mangiù aiuta a scegliere dove mangiare in tutta Italia: una guida dei locali (dati OpenStreetMap), menu e prezzi verificati, e un voto di gruppo da mandare su WhatsApp.

Questo repository contiene **solo il sito pubblicato** (GitHub Pages). Il codice sorgente dell'app (Expo / React Native) verrà spostato in un repository privato separato, da cui una build automatica aggiornerà questi file.

## Cosa c'è qui

| File | A cosa serve |
| --- | --- |
| `app.html` | Apre la guida completa di Mangiù (carica il bundle `lume-*.js`). |
| `lume-718907931722.js` | Bundle web compilato dell'app, quello attualmente in uso. |
| `index.html`, `voto.js`, `voto.css`, `catalogo.js` | Pagina leggera del voto di gruppo. |
| `menus.json` | Menu e prezzi verificati pubblicati. |
| `dati-italia.zip` | Guida dei locali italiani derivata da OpenStreetMap (ODbL 1.0). |
| `raccogli_menu.py` | Raccolta nazionale di fonti di menu e prezzi. |
| `leggi_menu_documenti.py` | Lettura di PDF e foto dei menu (OCR italiano). |
| `.github/workflows/` | `raccolta-menu.yml` e `documenti-menu.yml`, avviati a mano da GitHub Actions. |

## Aggiornare i dati

1. Avvia **Raccolta menu Italia** da GitHub Actions.
2. Avvia **Leggi PDF e foto dei menu** con l'ID della raccolta.
3. Oggi la pubblicazione in `menus.json` è ancora manuale: è il prossimo passo da automatizzare.

## Backend

Il voto di gruppo e gli account usano Supabase. In `catalogo.js` c'è solo la chiave pubblica (anon), pensata per stare nel browser.

## Licenza dei dati

Dati dei locali © OpenStreetMap contributors, Open Database License 1.0. Vedi `dati-italia.zip`.
