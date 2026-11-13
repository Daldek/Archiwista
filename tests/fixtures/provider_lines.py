"""The lines of the providers' terms, byte for byte as Nogat's DEV §20 words them.

Tests compare what a product carries with these constants, never with
Archiwista's own catalog (``archiwista.messages.legal``): a line merges with
the same line of another tool only when equal byte for byte, so a change of
the wording in the code must fail. The names follow the standard's marks:
the IMGW-PIB source (S) and the mark of processing (P); PMAXTP's source, mark
and monograph (PS, PP, M); the ČHMÚ credit (C), its short form on a GUI's
strip only (CK), and what was done with its data (CP), in Obserwator's stored
forms and in Archiwista's tables and charts; the terms of each service (RD,
RH, RK), links naming whose terms they are rather than their restatement
(DEV §20, ECO-065).
"""

IMGW_SOURCE = (
    "Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej"
    " – Państwowy Instytut Badawczy"
)
IMGW_PROCESSED = (
    "Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu"
    " Badawczego zostały przetworzone"
)
PMAXTP_SOURCE = (
    "Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej"
    " – Państwowy Instytut Badawczy, dane pochodzą ze strony"
    " https://klimat.imgw.pl/opady-maksymalne"
)
PMAXTP_PROCESSED = (
    "Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu"
    " Badawczego pochodzące ze strony https://klimat.imgw.pl/opady-maksymalne"
    " zostały przetworzone"
)
PMAXTP_MONOGRAPH = (
    "„Modele probabilistyczne opadów maksymalnych o określonym czasie trwania i"
    " prawdopodobieństwie przewyższenia – Projekt PMAXTP”, red. Bogdan"
    " Ozga-Zieliński, Instytut Meteorologii i Gospodarki Wodnej – Państwowy"
    " Instytut Badawczy, Warszawa 2022"
)
CHMI_SOURCE = (
    "Źródło danych: Český hydrometeorologický ústav (ČHMÚ), https://opendata.chmi.cz,"
    " licencja CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
)
CHMI_PROCESSED = "Dane ČHMÚ zostały przetworzone (normalizacja i zmiana formatu)"
CHMI_PROCESSED_VIEWS = (
    "Dane ČHMÚ zostały przetworzone (normalizacja i zmiana formatu, zestawienia i"
    " wykresy)"
)
CHMI_SHORT = "Źródło: ČHMÚ, CC BY 4.0"
IMGW_TERMS_PUBLIC_DATA = (
    "Regulamin danych IMGW-PIB: https://danepubliczne.imgw.pl/regulations"
)
IMGW_TERMS_HYDRO = (
    "Regulamin serwisu hydrologicznego IMGW-PIB: https://hydro.imgw.pl/#/regulamin"
)
IMGW_TERMS_PMAXTP = "Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne"
