// Kamienie milowe akcji Dekoracji (2026-10-29) — etykiety i klasy stanow, wspolne
// dla ekranu akcji (displays_akcja.js) i Gantta (displays.js). Stan liczy serwer
// (`stan_etapu()`, dzien lokalny serwera); tu tylko tekst i kolor.
const STANY_ETAPU = {
    bez_terminu: ['Bez terminu', ''], nie_dotyczy: ['Nie dotyczy', ''],
    planowany: ['Zaplanowany', ''], w_toku: ['W toku', 'w-toku'],
    konczy_sie: ['⏳ Kończy się', 'konczy-sie'], po_terminie: ['⚠ Po terminie', 'po-terminie'],
};
