"""
Worldwide dispatcher: given a country code, routes to the right directory
source. Any country NOT in this registry returns an empty list, which
main.py treats exactly like --skip-directory — it just falls straight
through to the Google Maps fallback for that run. Nothing breaks for an
unmapped country; it just doesn't get the directory-first speed/richness
boost.

TWO NETWORKS COVER ~137 COUNTRIES BETWEEN THEM:

1. MisterWhat — confirmed directly for GB only (category+city browsing,
   email NOT login-gated — "show email" is a client-side toggle). The
   other 11 domains are the same platform, unverified beyond that.

2. "Global Business Directory LLC" network (directory_gbd.py) — Yellosa
   (ZA) confirmed directly; BusinessList.com.ng (Nigeria) independently
   checked and found to be the exact same software, which is what
   justifies extending to the network's other ~125 advertised domains
   here. Email IS login-gated on this network (checked on Yellosa) —
   worse for email specifically than MisterWhat, but covers far more
   countries and gives richer per-listing data (VAT number, employee
   band, established year) either way.

Where a country could go to either network, MisterWhat is kept (better
email story) for the ones already wired up: GB, US, AU, NL, PL, PT, BR,
AR, FR, DE, DK, CA. GBD fills in everywhere else.

VERIFIED DIRECTLY (page structure checked against the live site, not
assumed): ZA, NG (both GBD), GB (MisterWhat). Everything else rides on
"same confirmed platform, different domain" confidence, not independent
verification — the code degrades gracefully (empty list -> Maps
fallback) rather than breaking if a specific unverified domain turns out
to differ.
"""

from scraper.directory_gbd import scrape_directory_leads as _scrape_gbd
from scraper.directory_misterwhat import scrape_directory_leads as _scrape_misterwhat

MISTERWHAT_DOMAINS = {
    "GB": "misterwhat.co.uk",   # verified directly
    "US": "misterwhat.com",
    "AU": "misterwhat-au.com",
    "FR": "misterwhat.fr",
    "DE": "misterwhat.de",
    "NL": "misterwhat.nl",
    "DK": "misterwhat.dk",
    "PL": "misterwhat.pl",
    "PT": "misterwhat.pt",
    "BR": "misterwhat.com.br",
    "AR": "misterwhat.com.ar",
    "CA": "ca.misterwhat.com",
}

# "Global Business Directory" network — ~125 countries, same platform as
# Yellosa (ZA, verified) and BusinessList.com.ng (NG, verified). Excludes
# any country already covered by MISTERWHAT_DOMAINS above.
GBD_DOMAINS = {
    "ZA": "www.yellosa.co.za",  # verified directly
    "NG": "www.businesslist.com.ng",  # verified directly

    # Asia
    "AM": "www.armeniayp.com", "AZ": "www.azerbaijanyp.com", "BD": "www.bangladeshyp.com",
    "BN": "www.bruneiyp.com", "KH": "www.cambodiayp.com", "CN": "www.chinayello.com",
    "GE": "www.georgiayp.com", "HK": "www.yelo.hk", "IN": "www.yelu.in",
    "ID": "www.indonesiayp.com", "JP": "www.japanyello.com", "KZ": "www.kazakhstanyp.com",
    "KG": "www.yelo.com.kg", "LA": "www.laosyp.com", "MY": "www.businesslist.my",
    "MV": "www.maldivesyp.com", "MM": "www.myanmaryp.com", "NP": "www.nepalyp.com",
    "PK": "www.businesslist.pk", "PH": "www.businesslist.ph", "SG": "www.yelu.sg",
    "KR": "www.southkoreayp.com", "LK": "www.lankayp.com", "TW": "www.taiwanyello.com",
    "TH": "www.thaiyello.com", "UZ": "www.uzbekistanyp.com", "VN": "www.vietnamyello.com",

    # Middle East
    "BH": "www.bahrainyellow.com", "EG": "www.egyptyello.com", "AE": "www.yello.ae",
    "IR": "www.iranyell.com", "IL": "www.israeliyp.com", "JO": "www.jordanyp.com",
    "KW": "www.kuwaityello.com", "LB": "www.yelleb.com", "OM": "www.omanyp.com",
    "QA": "www.qataryello.com", "SA": "www.saudiayp.com", "SY": "www.syriayp.com",
    "YE": "www.yemenyp.com",

    # Africa (ZA already above)
    "DZ": "www.algeriayp.com", "BJ": "www.beninyp.com", "BW": "www.localbotswana.com",
    "CM": "www.businesslist.co.cm", "TD": "www.chadyp.com", "CD": "www.congoyp.com",
    "DJ": "www.djiboutiyp.com", "ET": "www.ethyp.com", "GA": "www.yelu.ga",
    "GH": "www.ghanayello.com", "CI": "www.yelloci.com", "KE": "www.businesslist.co.ke",
    "LS": "www.lesothoyp.com", "LY": "www.libyayp.com", "MG": "www.madayp.com",
    "MW": "www.malawiyp.com", "ML": "www.maliyp.com", "MR": "www.mauritaniayp.com",
    "MU": "www.yelo.mu", "MA": "www.yelo.ma", "MZ": "www.mozambiqueyp.com",
    "NA": "www.namibiayp.com", "NE": "www.nigeryp.com", "RW": "www.rwandayp.com",
    "SN": "www.yelu.sn", "SC": "www.seychellesyp.com", "SD": "www.sudanyp.com",
    "TZ": "www.tanzapages.com", "TG": "www.togoyp.com", "TN": "www.tunisiayp.com",
    "UG": "www.yellow.ug", "ZM": "www.zambiayp.com", "ZW": "www.zimbabweyp.com",

    # Europe (NL/PL/PT/GB already on MisterWhat)
    "AL": "www.albaniayp.com", "AT": "www.austriayp.com", "BY": "www.yelo.by",
    "BE": "www.belgiumyp.com", "HR": "www.croatiayp.com", "CY": "www.cypindex.com",
    "EE": "www.estoniayp.com", "FI": "www.yellofi.com", "IS": "www.yelu.is",
    "IE": "www.irelandyp.com", "LT": "www.imoniukontaktai.lt", "LU": "www.luxyello.com",
    "MT": "www.maltayp.com", "NO": "www.yelono.com", "RO": "www.romaniayp.com",
    "SK": "www.slovakiayp.com", "SI": "www.sloveniayp.com", "SE": "www.swedyello.com",
    "CH": "www.swissyello.com", "TR": "www.turkishyello.com",

    # Australia region (AU already on MisterWhat)
    "FJ": "www.fijiyp.com", "NZ": "www.businesslist.nz", "PG": "www.pngyp.com",

    # North America (CA already on MisterWhat)
    "BS": "www.bahamasindex.com", "BB": "www.barbadosindex.com", "BZ": "www.yelu.bz",
    "KY": "www.caymanlist.com", "CR": "www.yelu.cr", "CU": "www.yellocu.com",
    "DO": "www.yelu.do", "SV": "www.elsalvadoryp.com", "GD": "www.grenadaindex.com",
    "GP": "www.guadeloupeindex.com", "GT": "www.gtyello.com", "HN": "www.yelu.hn",
    "JM": "www.jamaicaindex.com", "MQ": "www.martiniqueindex.com", "MX": "www.yelo.com.mx",
    "NI": "www.yelu.com.ni", "PA": "www.yelupa.com", "PR": "www.puertoricoindex.com",
    "LC": "www.saintluciaindex.com", "TT": "www.tntyellow.com",

    # South America (BR/AR already on MisterWhat)
    "BO": "www.boliviayp.com", "CL": "www.yelu.cl", "CO": "www.yelu.com.co",
    "EC": "www.yelu.ec", "GY": "www.guyanaindex.com", "PY": "www.yeloparaguay.com",
    "PE": "www.peruyello.com", "SR": "www.surinamyp.com", "UY": "www.yelu.uy",
    "VE": "www.venezuelayello.com",
}


def scrape_directory_leads(niche: str, location: str, max_results: int = 50, country: str = "ZA") -> list[dict]:
    country = (country or "").strip().upper()

    mw_domain = MISTERWHAT_DOMAINS.get(country)
    if mw_domain:
        return _scrape_misterwhat(mw_domain, niche, location, max_results=max_results)

    gbd_domain = GBD_DOMAINS.get(country)
    if gbd_domain:
        return _scrape_gbd(gbd_domain, niche, location, max_results=max_results)

    return []  # no directory mapped — main.py falls through to Maps entirely for this run
