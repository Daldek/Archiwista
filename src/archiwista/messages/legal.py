"""The lines the data providers' terms prescribe (Nogat DEV §20, ECO-060, ECO-065).

Every product of Archiwista with data of IMGW-PIB or ČHMÚ carries them verbatim:
the Polish wording the IMGW-PIB terms require (danepubliczne.imgw.pl §5 ust. 3
and 4, the terms of the PMAXTP project), the links to those terms and the
credit CC BY 4.0 requires of ČHMÚ, so a line equal byte for byte merges with the
same line of another tool. They keep that wording in every language: in an
English context the Polish line stays (DEV §20). The Polish text is the English
one by design; the guard test allows it for this area only. GUGiK's G and
ČÚZK's Z (DEV-20.9, DEV-20.11) are templates: the products and days of the
data they credit are a producer's, so Archiwista never fills them itself and
uses them only to recognise the lines a station catalog carries.
``archiwista.attribution`` chooses the lines of a product; nothing else holds
them (A-ADR-055).
"""

from archiwista.messages import Text

_IMGW = "Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy"
_IMGW_OF = (
    "Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego"
)
_PMAXTP_PAGE = "https://klimat.imgw.pl/opady-maksymalne"
_CHMI_PROCESSED = "Dane ČHMÚ zostały przetworzone"


def _same(text: str) -> Text:
    """Return an entry whose two languages are the one prescribed wording."""
    return Text(text, text)


MESSAGES = {
    # S and P: data of danepubliczne.imgw.pl and hydro.imgw.pl.
    "imgw_source": _same(f"Źródłem pochodzenia danych jest {_IMGW}"),
    "imgw_processed": _same(f"Dane {_IMGW_OF} zostały przetworzone"),
    # PS, PP and M: PMAXTP, whose terms replace S and P.
    "pmaxtp_source": _same(
        f"Źródłem pochodzenia danych jest {_IMGW}, dane pochodzą ze strony"
        f" {_PMAXTP_PAGE}"
    ),
    "pmaxtp_processed": _same(
        f"Dane {_IMGW_OF} pochodzące ze strony {_PMAXTP_PAGE} zostały przetworzone"
    ),
    "pmaxtp_monograph": _same(
        "„Modele probabilistyczne opadów maksymalnych o określonym czasie trwania"
        " i prawdopodobieństwie przewyższenia – Projekt PMAXTP”, red. Bogdan"
        f" Ozga-Zieliński, {_IMGW}, Warszawa 2022"
    ),
    # C and CP: ČHMÚ under CC BY 4.0. CP names what was done: Obserwator's
    # stored forms (its own wording), and Archiwista's tables and charts of them.
    "chmi_source": _same(
        "Źródło danych: Český hydrometeorologický ústav (ČHMÚ),"
        " https://opendata.chmi.cz, licencja CC BY 4.0"
        " (https://creativecommons.org/licenses/by/4.0/)"
    ),
    "chmi_processed": _same(f"{_CHMI_PROCESSED} (normalizacja i zmiana formatu)"),
    "chmi_processed_views": _same(
        f"{_CHMI_PROCESSED} (normalizacja i zmiana formatu, zestawienia i wykresy)"
    ),
    # G and Z: GUGiK and ČÚZK data, here the state borders against which
    # Obserwator's station catalogs check every position (PRG, RÚIAN).
    "gugik_source": _same(
        "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, {products}"
        " (wytworzono {period}, pozyskano {date}); dane przetworzone"
    ),
    "cuzk_source": _same(
        "Źródło: Český úřad zeměměřický a katastrální (ČÚZK), {products}"
        " (pozyskano {date}), licencja CC BY 4.0"
        " (https://creativecommons.org/licenses/by/4.0/); dane przetworzone"
    ),
    # RD, RH and RK: the links to the IMGW-PIB terms that apply, never a summary
    # of them (ECO-065), each naming whose terms it links.
    "imgw_terms_public_data": _same(
        "Regulamin danych IMGW-PIB: https://danepubliczne.imgw.pl/regulations"
    ),
    "imgw_terms_hydro": _same(
        "Regulamin serwisu hydrologicznego IMGW-PIB: https://hydro.imgw.pl/#/regulamin"
    ),
    "imgw_terms_pmaxtp": _same(f"Regulamin danych PMAXTP: {_PMAXTP_PAGE}"),
}
