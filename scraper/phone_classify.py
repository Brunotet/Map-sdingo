"""
Classifies a phone number as mobile (WhatsApp-capable) vs landline vs
unknown, for the reachability filter in main.py: a lead with no email
and a landline-only number can't be contacted via email OR WhatsApp, so
there's no point keeping it in the results.

Uses Google's phonenumbers library — a Python port of libphonenumber,
free, no API calls, works fully offline against bundled per-country
metadata. This is deliberately used INSTEAD of hand-rolled per-country
prefix tables: researching mobile-vs-landline prefix ranges by hand for
every one of the ~140 countries in the directory registry would be slow
and error-prone, where this is already accurate, already maintained, and
covers essentially every country in the world, not just the ones we have
directories for.

Verified directly against South Africa's real prefixes (matches exactly
what a person familiar with SA numbering would expect): 011, 012, 021
(Johannesburg/Pretoria/Cape Town area codes) -> landline. 066, 071, 072,
082 -> mobile.

WhatsApp only runs on mobile numbers (not landlines, not toll-free, and
in practice not VOIP for ordinary consumer WhatsApp) — MOBILE and
FIXED_LINE_OR_MOBILE (a genuinely ambiguous category some countries'
numbering plans have — a number that could be either, not a parsing
failure) are both treated as "mobile" here, since either way WhatsApp
usage is plausible. Everything else (FIXED_LINE, TOLL_FREE, VOIP, PAGER,
PREMIUM_RATE, SHARED_COST, etc.) is "landline". Anything that fails to
parse or doesn't validate is "unknown" — treated the same as "landline"
by the reachability filter (i.e. an email becomes required), since an
unparseable number is not a confirmed WhatsApp channel either.
"""

import phonenumbers
from phonenumbers import PhoneNumberType

MOBILE_TYPES = {PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE}


def classify_phone(phone: str, default_region: str = "ZA") -> str:
    """Returns "mobile" | "landline" | "unknown". `default_region` should
    be the run's country code — used only when `phone` doesn't already
    include a country code (e.g. "021 461 4456" needs it, "+27 21 461
    4456" doesn't)."""
    if not phone or not phone.strip():
        return "unknown"
    try:
        parsed = phonenumbers.parse(phone, default_region)
    except phonenumbers.NumberParseException:
        return "unknown"

    if not phonenumbers.is_valid_number(parsed):
        return "unknown"

    return "mobile" if phonenumbers.number_type(parsed) in MOBILE_TYPES else "landline"
