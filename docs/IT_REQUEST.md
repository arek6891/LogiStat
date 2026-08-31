# Zgłoszenie do IT — publikacja aplikacji pod domenami (DNS + reverse proxy)

Zgłaszający: Arkadiusz Sobczyk

## Kontekst

Rozdzielamy środowiska na testowe i produkcyjne dla dwóch aplikacji:

- **Okno zwrotowe** (Returns Hub)
- **LogiStat** — aplikacja do post-processu Beeline

Serwery:

| Serwer | Rola | Nazwa hosta |
|---|---|---|
| `10.153.1.31` | testowy | `ploptmtst01` |
| `10.153.1.30` | produkcyjny | — |

Prosimy o utworzenie nazw DNS wskazujących na firmowy reverse proxy (`10.15.12.67` —
ten sam, który obsługuje dziś `returns-hub.logwin-logistics.com.pl`) i skierowanie ruchu
na serwery i porty podane w tabeli poniżej. SSL, jak dotychczas, terminuje się na proxy.

---

## Do skonfigurowania

| # | Aplikacja | Środowisko | Adres dla użytkowników | Serwer backend | Port backendu |
|---|---|---|---|---|---|
| 1 | Okno zwrotowe | TEST | `https://returns-hub-test.logwin-logistics.com.pl/` | `10.153.1.31` | `3000/tcp` |
| 2 | Okno zwrotowe | PROD | `https://returns-hub-prod.logwin-logistics.com.pl/` | `10.153.1.30` | `3000/tcp` |
| 3 | LogiStat | TEST | `https://logistat-test.logwin-logistics.com.pl/` | `10.153.1.31` | `5001/tcp` |
| 4 | LogiStat | PROD | `https://logistat-prod.logwin-logistics.com.pl/` | `10.153.1.30` | `5001/tcp` |

Ruch od proxy do backendu — zwykły HTTP (bez SSL), tak jak działa to dziś dla Okna zwrotowego.

### Uwagi do poszczególnych pozycji

**Poz. 1 — to zmiana nazwy istniejącego wpisu.** Dziś `https://returns-hub.logwin-logistics.com.pl/`
kieruje na serwer testowy `10.153.1.31`. Prosimy o zmianę nazwy na `returns-hub-test`.
Pytanie: czy stara nazwa może na okres przejściowy przekierowywać na nową, żeby nie zaskoczyć
użytkowników, którzy mają ją w zakładkach?

**Poz. 2 i 4 — serwer produkcyjny `10.153.1.30` jest jeszcze pusty.** Aplikacje nie są tam
wdrożone, więc do momentu naszego wdrożenia te dwa adresy będą zwracać błąd. Wpisy DNS i
konfigurację proxy można przygotować z wyprzedzeniem — damy znać, gdy wdrożymy.

### Dodatkowo potrzebne

- **Firewall:** przepuszczenie ruchu z proxy `10.15.12.67` na backendy:
  - Okno zwrotowe: `10.153.1.31:3000`, `10.153.1.30:3000`
  - LogiStat: `10.153.1.31:5001-5005`, `10.153.1.30:5001-5005`

  Dla LogiStat prosimy o **zakres `5001-5005`**, a nie pojedynczy port. Dziś aplikacja
  używa wyłącznie `5001`; zapas jest po to, aby ewentualny późniejszy podział aplikacji
  na osobne usługi nie wymagał kolejnego zgłoszenia. Same wpisy DNS dotyczą tylko portu
  `5001` — pozostałe porty z zakresu zostają nieużywane do czasu, gdy o nie poprosimy.
- **Limit rozmiaru żądania na proxy: min. 50 MB** dla adresów LogiStat
  (aplikacja przyjmuje import plików Excel/CSV). Dla Okna zwrotowego bez zmian.
- **Potwierdzenie, że porty `5001-5005/tcp` są wolne na `10.153.1.30`.**
  Na serwerze testowym `10.153.1.31` cały ten zakres jest wolny — sprawdzone.

### Czego nie potrzebujemy

- Certyfikatów SSL na naszych serwerach — SSL terminuje proxy.
- Otwierania portów 80/443 na `10.153.1.30` i `10.153.1.31`.
- Publikowania portów `3002` (Okno zwrotowe) i `5000` (LogiStat) — patrz uwagi techniczne.
- Portów dla baz danych — bazy działają wyłącznie lokalnie na serwerze (`127.0.0.1`)
  i komunikują się z aplikacją po wewnętrznej sieci Dockera. Nie wymagają żadnego
  portu dostępnego z zewnątrz, teraz ani po planowanej migracji na PostgreSQL.

---

## Dostęp do serwera produkcyjnego `10.153.1.30`

Do wdrożenia aplikacji na produkcji potrzebujemy dostępu SSH do `10.153.1.30`
dla użytkownika **`optmtst_user`** (uwierzytelnianie kluczem — takie samo jak na serwerze
testowym `10.153.1.31`, gdzie dostęp już mamy i działa).

Obecnie logowanie jest odrzucane (`Permission denied (publickey,password)`), choć port 22
jest otwarty.

---

## Uwagi techniczne (dlaczego te, a nie inne porty)

**Okno zwrotowe — proxy potrzebuje tylko portu `3000`.**
Port `3002` to backend API, do którego ruch trafia **wewnątrz** serwera: kontener frontendu
ma własny nginx, który przekierowuje ścieżki `/api/` na backend po wewnętrznej sieci Dockera.
Z zewnątrz wystarczy port `3000` — sprawdzone: `http://10.153.1.31:3000/api/` odpowiada
z backendu. Portu `3002` nie trzeba publikować.

**LogiStat — proxy potrzebuje tylko portu `5001`.**
To jedna aplikacja w jednym procesie, która serwuje jednocześnie strony HTML i API —
nie ma osobnego portu dla frontendu i backendu. Port `5000` to port **wewnątrz kontenera**;
na zewnątrz Docker wystawia go jako `5001` (mapowanie `5001:5000`). Z sieci łączymy się
wyłącznie na `5001`.

**Port `5000` na serwerze testowym `10.153.1.31` jest zajęty przez inną aplikację**
(kontener `jewelry_tracker`). Ponieważ LogiStat potrzebuje tylko portu `5001`, który jest
wolny, nie ma konfliktu i nie trzeba nic przenosić.
