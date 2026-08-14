"""Merchant normalization and categorization.

Card descriptors carry a payment-processor prefix, a store number, a city, a
state and sometimes a phone number or URL -- ``TST* EXAMPLE ICE HOUSE - EA
SOMETOWN TX`` and ``SQ *TACOS EXAMPLE GRILL Sometown TX`` are the same kind
of string. Two passes handle that:

1. ``RULES`` -- ordered (pattern, merchant, category) triples matched against
   the raw descriptor. This is where anything ambiguous or high-volume is
   pinned down exactly. Prefix stripping alone would turn ``LYFT *RIDE WED
   11PM`` into "Ride Wed 11pm", so aggregators are matched, not stripped.
2. ``clean()`` + ``CATEGORY_HINTS`` -- for the long tail, which is most of
   the distinct descriptors and where most appear exactly once, strip the
   noise generically and infer a category from the surviving name.

Anything the second pass can't place is left as ``uncategorized`` rather than
guessed at; ``python -m statementproof.run --uncategorized`` lists what is missing,
worst-by-spend first, so this file can be extended against real gaps.
"""

from __future__ import annotations

import re

from . import config

USER_RULES = config.load()

# --- categories -------------------------------------------------------------
GROCERIES = "Groceries"
DINING = "Dining & Delivery"
GAS = "Gas & Fuel"
TRANSPORT = "Transport"
TRAVEL = "Travel"
SHOPPING = "Shopping"
ENTERTAINMENT = "Entertainment"
RECREATION = "Recreation & Sports"
SUBSCRIPTIONS = "Subscriptions"
UTILITIES = "Utilities"
INSURANCE = "Insurance"
HEALTH = "Health & Pharmacy"
PERSONAL = "Personal Care"
AUTO = "Auto"
GAMBLING = "Gambling"
FEES = "Fees & Interest"
GOVERNMENT = "Government & Taxes"
HOUSING = "Housing"
HOUSEHOLD = "Household"
PEOPLE = "People & Services"
INCOME = "Income"
REIMBURSEMENT = "Reimbursements"
ONEOFF = "One-off deposits"
TRANSFERS = "Transfers"
CASH = "Cash & ATM"
REFUNDS = "Refunds"
UNCATEGORIZED = "uncategorized"

# --- explicit rules, checked in order ---------------------------------------
# (regex against the upper-cased raw descriptor, canonical merchant, category)
RULES: list[tuple[str, str, str]] = [
    # --- checking: income, transfers, loans -------------------------------
    (r"\bPAYROLL\b|DIR DEP|DIRECT DEP", "Payroll", INCOME),
    (r"IRS\s+TREAS.*TAX REF", "IRS tax refund", INCOME),
    (r"PAYMENT TO CHASE CARD", "Chase card payment", TRANSFERS),
    (r"DISCOVER\s+E-PAYMENT", "Discover card payment", TRANSFERS),
    (r"TRUIST CK WEBXFR", "Truist transfer", TRANSFERS),
    (r"MANUAL DB-BKRG", "Brokerage transfer", TRANSFERS),
    # Buy-now-pay-later instalments buy goods; they are not an account transfer.
    (r"PAYPAL INST XFER|PYPL PAYIN", "PayPal (Pay in 4)", SHOPPING),
    (r"ONLINE (DOMESTIC )?WIRE FEE", "Wire fee", FEES),
    (r"ONLINE (DOMESTIC )?WIRE TRANSFER", "Wire transfer", TRANSFERS),
    (r"NON-CHASE ATM FEE|SERVICE FEE|MONTHLY SERVICE|OVERDRAFT FEE", "Chase fee", FEES),
    (r"ATM WITHDRAW|NON-CHASE ATM", "ATM withdrawal", CASH),
    (r"SETOYOTA|TOYOTA FIN|EZP AUTO FINAN", "Toyota Financial (auto loan)", AUTO),
    (r"ASI LLOYDS", "ASI Lloyds (insurance)", INSURANCE),

    # --- aggregators / delivery -------------------------------------------
    (r"DOORDASH|DD \*", "DoorDash", DINING),
    (r"GRUBHUB|UBER ?EATS|POSTMATES|CAVIAR", "Food delivery", DINING),
    (r"LYFT", "Lyft", TRANSPORT),
    (r"UBER", "Uber", TRANSPORT),
    (r"MTA\*|NYCT PAYGO", "MTA (NYC transit)", TRANSPORT),
    (r"LIME\*|BIRD ", "Lime / Bird", TRANSPORT),

    # --- gas & convenience -------------------------------------------------
    (r"SHELL", "Shell", GAS),
    (r"EXXON", "Exxon", GAS),
    (r"CHEVRON|TEXACO|VALERO|CONOCO|MARATHON PETRO", "Gas station", GAS),
    (r"BUC-?EE", "Buc-ee's", GAS),
    (r"LOVE'?S #", "Love's", GAS),
    (r"CIRCLE K|7-ELEVEN|QUIKTRIP|RACETRAC", "Convenience store", GAS),

    # --- groceries ----------------------------------------------------------
    (r"H-E-B|\bHEB\b", "H-E-B", GROCERIES),
    (r"CENTRAL MARKET", "Central Market", GROCERIES),
    (r"KROGER|RANDALLS|WHOLE FOODS|TRADER JOE|ALDI|SPROUTS", "Grocery store", GROCERIES),

    # --- pharmacy & health --------------------------------------------------
    (r"CVS/?PHARMACY|\bCVS\b", "CVS", HEALTH),
    (r"WALGREENS|RITE AID", "Walgreens", HEALTH),
    (r"DENTAL|DENTIST|ORTHODON", "Dental", HEALTH),
    (r"MEDICAL|CLINIC|HOSPITAL|URGENT CARE|PHARMACY", "Medical", HEALTH),

    # --- restaurants (high volume, named) -----------------------------------
    (r"TIM HORTONS", "Tim Hortons", DINING),
    (r"MCDONALD", "McDonald's", DINING),
    (r"TACO BELL", "Taco Bell", DINING),
    (r"PIZZA HUT", "Pizza Hut", DINING),
    (r"WHATABURGER", "Whataburger", DINING),
    (r"POPEYES", "Popeyes", DINING),
    (r"DUNKIN", "Dunkin'", DINING),
    (r"POTBELLY", "Potbelly", DINING),
    (r"JAMBA JUICE", "Jamba Juice", DINING),
    (r"JERSEY MIKES", "Jersey Mike's", DINING),
    (r"STARBUCKS", "Starbucks", DINING),
    (r"CHIPOTLE", "Chipotle", DINING),

    # --- subscriptions & digital -------------------------------------------
    (r"NETFLIX", "Netflix", SUBSCRIPTIONS),
    (r"SPOTIFY", "Spotify", SUBSCRIPTIONS),
    (r"APPLE\.COM/BILL|ITUNES", "Apple", SUBSCRIPTIONS),
    (r"HULU|DISNEY PLUS|HBO ?MAX|\bMAX\.COM|PARAMOUNT\+|PEACOCK", "Streaming", SUBSCRIPTIONS),
    (r"YOUTUBE ?PREMIUM|GOOGLE \*?YOUTUBE", "YouTube", SUBSCRIPTIONS),
    (r"AUDIBLE|KINDLE UNLIM|CHATGPT|OPENAI|ANTHROPIC|CLAUDE", "Digital subscription", SUBSCRIPTIONS),

    # --- entertainment ------------------------------------------------------
    (r"STEAMGAMES|STEAM PURCHASE", "Steam", ENTERTAINMENT),
    (r"PLAYSTATION", "PlayStation", ENTERTAINMENT),
    (r"NINTENDO", "Nintendo", ENTERTAINMENT),
    (r"XBOX|MICROSOFT ?\*?GAME", "Xbox", ENTERTAINMENT),
    (r"REGAL CINEMAS|REG GREENWAY|EDWARD THEATER|\bAMC\b|CINEMARK|CINEMA", "Movie theater", ENTERTAINMENT),
    (r"TICKETMASTER|STUBHUB|SEATGEEK|VIVID SEATS", "Ticketing", ENTERTAINMENT),

    # --- recreation ---------------------------------------------------------
    (r"GOLF|TOPGOLF|DRIVING RANGE", "Golf", RECREATION),
    (r"\bGYM\b|FITNESS|LIFE TIME|PLANET FIT|CLIMBING", "Gym & fitness", RECREATION),

    # --- gambling -----------------------------------------------------------
    (r"FANDUEL|DRAFTKINGS|BETMGM|CAESARS SPORTS", "Sportsbook", GAMBLING),

    # --- utilities ----------------------------------------------------------
    (r"COMCAST|XFINITY", "Comcast / Xfinity", UTILITIES),
    (r"SPECTRUM|COX COMM|CENTURYLINK", "Internet & cable", UTILITIES),
    (r"OHMCONNECT|RELIANT|CENTERPOINT|TXU|GEXA|CON ?EDISON|DUKE ENERGY|PG&E",
     "Electricity", UTILITIES),
    (r"PAYMENTUS", "Utility payment", UTILITIES),
    (r"\bAT&T\b|VERIZON|T-MOBILE|MINT MOBILE", "Phone", UTILITIES),
    (r"WATER DEPT|WATER UTIL|\bCITY OF [A-Z]", "Water / city services", UTILITIES),

    # --- insurance ----------------------------------------------------------
    (r"PROGRESSIVE", "Progressive (insurance)", INSURANCE),
    (r"GEICO|STATE FARM|ALLSTATE|USAA|LEMONADE INS", "Insurance", INSURANCE),

    # --- auto ---------------------------------------------------------------
    (r"MISTER CAR WASH|CAR WASH", "Car wash", AUTO),
    (r"SAFELITE", "Safelite", AUTO),
    (r"DISCOUNT TIRE|AUTOZONE|O'?REILLY AUTO|NTB |FIRESTONE|JIFFY LUBE", "Auto parts & service", AUTO),
    (r"U-?HAUL", "U-Haul", AUTO),
    (r"PARKING|PARKMOBILE|SP\+ |EZ ?TAG|TOLL", "Parking & tolls", TRANSPORT),

    # --- travel -------------------------------------------------------------
    (r"UNITED 0\d|UNITED\.COM|AMERICAN AIR|DELTA AIR|SOUTHWEST AIR|SPIRIT AIR|FRONTIER AIR",
     "Airline", TRAVEL),
    (r"CHASE TRAVEL|TRIPCHRG", "Chase Travel", TRAVEL),
    (r"MARRIOTT|HILTON|HYATT|AIRBNB|VRBO|BOOKING\.COM|EXPEDIA|HOTEL", "Lodging", TRAVEL),

    # --- personal care ------------------------------------------------------
    (r"FLOYD'?S 99|BARBER|SUPERCUTS|GREAT CLIPS", "Barber", PERSONAL),
    (r"NAIL|SPA\b|MASSAGE|SALON", "Salon & spa", PERSONAL),

    # --- shopping -----------------------------------------------------------
    (r"AMAZON|AMZN", "Amazon", SHOPPING),
    (r"TARGET\b", "Target", SHOPPING),
    (r"WALMART|WM SUPERCENTER", "Walmart", SHOPPING),
    (r"BEST BUY", "Best Buy", SHOPPING),
    (r"MICRO CENTER", "Micro Center", SHOPPING),
    (r"NEWBALANCE|NIKE|ADIDAS|FOOT ?LOCKER|LULULEMON", "Apparel", SHOPPING),
    (r"UPS STORE|FEDEX|USPS", "Shipping", SHOPPING),
    (r"GROUPON", "Groupon", SHOPPING),
    (r"HOME DEPOT|LOWES|ACE HARDWARE|IKEA", "Home improvement", SHOPPING),
    (r"UNIQLO|TILLYS|CRAZY SHIRTS|OLD NAVY|GAP\b|H&M\b", "Apparel", SHOPPING),
    (r"PETSMART|PETCO|CHEWY", "Pet supplies", SHOPPING),
    (r"APPLE STORE", "Apple Store", SHOPPING),
    (r"WARBY PARKER|LENSCRAFTERS|EYE ?CARE", "Vision", HEALTH),

    # --- government / taxes -------------------------------------------------
    (r"\bDMV\b|DEPT OF MOTOR|DEPT OF PUBLIC SAFETY|VEHREG|\bTX MV\b|\bCO TX MV\b",
     "Motor vehicle dept", GOVERNMENT),
    (r"NCOURT|MUNICIPAL COURT|COUNTY CLERK|COUNTY TAX|CO(UNTY)? TX-", "County fees", GOVERNMENT),
    (r"IRS USATAXPYMT|TAX PAYMENT", "Tax payment", GOVERNMENT),

    # --- more auto ----------------------------------------------------------
    (r"KWIK KAR|LUBE ?& ?TUNE|OIL CHANGE|BRAKE|TRANSMISSION", "Auto service", AUTO),
    (r"AUTO TRANSPORT|MONTWAY|AUTO STORAGE", "Auto transport & storage", AUTO),
    (r"DRIVING SCHOOL|DRIVERS ED|DEFENSIVE DRIVING", "Driving school", AUTO),

    # --- more dining / venues ----------------------------------------------
    (r"CHICK-?FIL-?A", "Chick-fil-A", DINING),
    (r"SONIC DRIVE", "Sonic", DINING),
    (r"ARMK|AMK |CONCESSION|CONC BA|CENTER CONC", "Venue concessions", DINING),
    (r"DAVE ?& ?BUSTERS|HOUSE OF BLUES|LIVESTOCK SHOW|\bZOO\b|AQUARIUM",
     "Attractions & venues", ENTERTAINMENT),
    (r"MUSIC CENTER|PERFORMING ARTS|EVENT MERCHANDISING", "Live music & arts", ENTERTAINMENT),
    (r"BARNES & NOBLE|BOOKS-?A-?MILLION", "Books & media", SHOPPING),
    (r"CALVINKLEIN|CALVIN KLEIN", "Apparel", SHOPPING),
    (r"COUNTRY CLUB|SIM RACING|PICKLEBALL", "Clubs & sports", RECREATION),
    (r"BLUECHEW|HIMS |ROMAN HEALTH", "Telehealth", HEALTH),
    (r"CHARGE UP|CHARGEPOINT|EVGO|ELECTRIFY AMERICA", "EV charging", GAS),

    # --- national chains, added from a second bank's statements --------------
    # Several are matched in truncated form: statements clip merchant names to a
    # fixed width, so "WHOLEFDS" and "Sephora Memori" are what actually prints.
    (r"WHOLEFDS|WHOLE FOODS", "Whole Foods", GROCERIES),
    (r"INSTACART", "Instacart", GROCERIES),
    (r"SEPHORA|\bULTA\b", "Sephora / Ulta", PERSONAL),
    (r"VICTORIA'?S SEC", "Victoria's Secret", SHOPPING),
    (r"TJ ?MAXX|MARSHALLS|ROSS DRESS|BURLINGTON STORES", "Off-price apparel", SHOPPING),
    (r"URBAN OUTFITTERS|ANTHROPOLOGIE|OLD NAVY|GAP STORES", "Apparel", SHOPPING),
    (r"GOODWILL|SALVATION ARMY", "Thrift store", SHOPPING),
    (r"WM SUPERCENTER", "Walmart", SHOPPING),
    (r"LUFTHAN|BRITISH AIRW|AIR ?FRANCE|EMIRATES", "Airline", TRAVEL),
    (r"UNITED 800932|UNITED AIRLINES", "United Airlines", TRAVEL),
    (r"^TM\s?\*", "Ticketmaster", ENTERTAINMENT),
    (r"AP GAS ?& ?ELECTRIC|AP GAS", "Electricity", UTILITIES),
    (r"METRO BY T ?MOB|METROPCS|CRICKET WIRELESS|BOOST MOBILE", "Phone", UTILITIES),
    (r"ALLIANZ", "Allianz (insurance)", INSURANCE),
    (r"WAFFLE HOUS|DENNYS|IHOP\b|CRACKER BARREL", "Diner", DINING),
    (r"365 VEND|CTLP\*|CANTALOUPE", "Vending machine", DINING),
    (r"GUN RANGE|SHOOTING RANGE", "Shooting range", RECREATION),
    (r"\bCASINO\b|LUXOR CAS", "Casino", GAMBLING),
    (r"AEROPUERTO|MIGRACION", "Airport & immigration fees", TRAVEL),
    (r"METAPAY", "Meta Pay", TRANSFERS),
]

# Some payment processors only serve one kind of business, which settles the
# category even when the merchant name itself is unrecognizable.
#   TST* -> Toast, a restaurant-only POS
#   SP   -> Shopify checkout, i.e. online retail
PROCESSOR_CATEGORY: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^TST\s?\*"), DINING),
    (re.compile(r"^SP[\s*](?!O\*)"), SHOPPING),
]

# --- person-to-person rails -------------------------------------------------
# Zelle/Venmo/Meta Pay/Apple Cash are payment *rails*, not merchants: money sent
# over them leaves for good, so it is spending, and what it bought is decided by
# the counterparty rather than the rail. Classifying the rail itself as a
# transfer (the way a card payment nets against its own purchases) would hide
# the largest fixed cost in this data.
P2P_SENT = re.compile(
    r"^(?:ZELLE PAYMENT TO|VENMO(?: PAYMENT)?|METAPAY|APPLE CASH SENT(?: MONE)?)\s*(.*)$", re.I
)
P2P_RECEIVED = re.compile(r"ZELLE PAYMENT FROM|VENMO CASHOUT|APPLE CASH RECEIVED", re.I)
# Trailing rail reference codes: "Jpm99B6Zh2Lz", "Bbt313653032", "25081420665".
P2P_REF = re.compile(r"\s*(?:JPM\w+|BBT\d+|COF\w+|BAC\w+|WEB ID:.*|\d{9,})\s*$", re.I)

# Counterparties whose payments are a known standing obligation -- a landlord,
# a cleaner, a shared-household payee. A statement descriptor carries only a
# first name and a rail reference code, so this can never be inferred; it has
# to be told to us. It is also personal data about third parties, which is why
# it lives in the user's config file and ships empty. See config.py.
PAYEE_CATEGORY: list = config.compiled_payees(USER_RULES)


# --- ACH ---------------------------------------------------------------------
# An ACH descriptor is a network-standard record rather than a bank's
# formatting choice, so this is the one piece of descriptor handling that is
# genuinely universal. Its tail carries a *volatile* per-transaction reference
# and a *stable* originator id:
#
#   Example Properties DES:WEB PMTS ID:AB12CD INDN:A Person CO ID:9876543210
#   Example Properties DES:WEB PMTS ID:EF34GH INDN:A Person CO ID:9876543210
#
# Keying on the raw text turns one landlord into a new merchant every month. In
# one real statement set, six variants of a single payee were 51% of all
# uncategorized spend. Stripping the tail collapses them, because the payee name
# in front of it is stable.
#
# The originator id is the better identity -- it survives a payee being renamed
# and is unique per originator -- so user rules can key on it directly.
ACH_TAIL = re.compile(
    r"\s+(?:DES:|INDN:|CO ID:|(?:PPD|CCD|WEB|TEL|ARC|IAT)\s*ID:).*$", re.I
)
ACH_CO_ID = re.compile(r"\bCO ID:\s*(\w+)", re.I)
ACH_TYPE_ID = re.compile(r"\b(?:PPD|CCD|WEB|TEL|ARC|IAT)\s*ID:\s*(\w+)", re.I)


def ach_originator(text: str):
    """The stable originator id of an ACH entry, if it has one."""
    hit = ACH_CO_ID.search(text) or ACH_TYPE_ID.search(text)
    return hit.group(1) if hit else None


def strip_ach_tail(text: str) -> str:
    """Drop the ACH reference block, keeping the payee name in front of it.

    Also removes ``INDN:`` -- the individual-name field, which holds the account
    holder's own name and has no business in a merchant label.
    """
    return ACH_TAIL.sub("", text).strip()


# ACH originator id -> (merchant, category), from the user's config.
ACH_RULES: dict = config.ach_rules(USER_RULES)


# --- inflows ----------------------------------------------------------------
# Money arriving is not all the same thing, and treating it as one number
# overstates earnings. Four distinct kinds show up here:
#   Income        -- payroll and tax refunds: money earned or returned
#   Reimbursements-- people paying you back, resale payouts: offsets, not income
#   Transfers     -- funding from an account the user already owns
#   One-off       -- an unattributed lump, neither recurring nor earned; kept
#                    visible rather than folded into either total
INFLOW_RULES: list = [
    (re.compile(r"\bPAYROLL\b|DIR DEP|DIRECT DEP", re.I), "Payroll", INCOME),
    (re.compile(r"IRS\s+TREAS.*TAX REF|TAX REF", re.I), "IRS tax refund", INCOME),
    (re.compile(r"INTEREST PAYMENT|INTEREST EARNED", re.I), "Interest earned", INCOME),
    (re.compile(r"TRUIST CK WEBXFR", re.I), "Truist transfer", TRANSFERS),
    (re.compile(r"MANUAL CR-BKRG|BKRG", re.I), "Brokerage transfer", TRANSFERS),
    (re.compile(r"TICKETMASTER", re.I), "Ticketmaster (resale payout)", REIMBURSEMENT),
    (re.compile(r"VENMO|PAYPAL|APPLE CASH", re.I), "Person-to-person received", REIMBURSEMENT),
    (re.compile(r"^DEPOSIT\b", re.I), "Deposit (unattributed)", ONEOFF),
]

# User merchant rules apply to inflows too, so an employer or a regular payer
# can be named without touching the shipped ruleset.
USER_INFLOW: list = config.compiled_merchants(USER_RULES)


def inflow(description: str) -> tuple[str, str]:
    """Classify money arriving in checking."""
    text = CHECKING_DATE_PREFIX.sub("", description).strip()
    # A user rule naming an employer or a known payer wins outright.
    for pattern, merchant, category in USER_INFLOW:
        if pattern.search(text):
            return merchant, category
    if P2P_RECEIVED.search(text.upper()):
        return "Zelle received", REIMBURSEMENT
    for pattern, merchant, category in INFLOW_RULES:
        if pattern.search(text):
            return merchant, category
    # Unknown credit: a merchant name here means money came back from them.
    originator = ach_originator(text)
    if originator and originator.upper() in ACH_RULES:
        return ACH_RULES[originator.upper()][0], INCOME
    for pattern, merchant, category in COMPILED:
        if pattern.search(text.upper()):
            return merchant, REIMBURSEMENT
    text = strip_ach_tail(text)
    return titlecase(clean(text)) or text, ONEOFF


def p2p(description: str) -> tuple[str, str] | None:
    """Classify a person-to-person payment by counterparty, or None."""
    raw = description.upper()
    if P2P_RECEIVED.search(raw):
        return "Zelle received", INCOME
    hit = P2P_SENT.match(raw.strip())
    if not hit:
        return None
    who = P2P_REF.sub("", hit.group(1)).strip(" -")
    if not who:
        return "Person-to-person payment", PEOPLE
    for pattern, label, category in PAYEE_CATEGORY:
        if pattern.match(who):
            return f"{label} ({titlecase(who)})", category
    return f"To {titlecase(who)}", PEOPLE

# User rules come first so a local guess always beats a shipped one.
COMPILED: list = config.compiled_merchants(USER_RULES) + [
    (re.compile(p), name, cat) for p, name, cat in RULES
]

# --- long-tail category inference, applied to the cleaned name --------------
CATEGORY_HINTS: list[tuple[str, str]] = [
    (r"PIZZA|TACO|TAQUERIA|BURGER|GRILL|CAFE|COFFEE|BAKER|BISTRO|KITCHEN|"
     r"RESTAURANT|CANTINA|SUSHI|RAMEN|BBQ|BAR\b|ALE HOUSE|BREWING|BREWERY|"
     r"DELI|DONUT|GELATO|PASTRY|JUICE|SMOOTHIE|CREAMERY|EATERY|DINER|"
     r"STEAKHOUSE|NOODLE|WINGS|CHICKEN|SANDWICH|BAGEL|CONCESSION|CONSESS", DINING),
    (r"MARKET|GROCER|FOOD STORE|SUPERMARK", GROCERIES),
    (r"ICE ?HOUSE|\bPUB\b|LOUNGE|TAVERN|SALOON|TAQUITO|CAFETERIA", DINING),
    (r"THEATER|THEATRE|MUSEUM|GALLERY|CONCERT|ARENA|STADIUM|TICKETS?", ENTERTAINMENT),
    (r"HOTEL|INN\b|RESORT|LODGE|HOSTEL|AIRLINE|AIRPORT|AIRWAYS", TRAVEL),
    (r"TRANSIT|SUBWAY CARD|RAIL|METRO|TAXI|CAB\b|SHUTTLE", TRANSPORT),
    (r"PHARMACY|DRUG|HEALTH|DOCTOR|\bMD\b|VISION|OPTICAL", HEALTH),
    (r"INSURANCE|\bINS\b", INSURANCE),
    (r"GOLF|SKATE|TENNIS|SPORTS|RECREATION|PARK\b", RECREATION),
]
COMPILED_HINTS = [(re.compile(p), cat) for p, cat in CATEGORY_HINTS]

# --- generic descriptor cleanup ---------------------------------------------
PROCESSOR_PREFIX = re.compile(
    r"^(SQ|TST|DD|WL|FSP|PYN|TM|CTLP|PY|SPO|GLF|UEP|OPY|CL|IN|PP|SP)\s?\*\s*", re.I
)
TRAILING_STATE = re.compile(r"\s+[A-Z]{2}\s*$")
PHONE = re.compile(r"\b(?:\d{3}[- ]?\d{3}[- ]?\d{4}|\d{10,})\b")
URL = re.compile(r"\b(?:HTTPS?://|WWW\.)?[A-Z0-9-]+\.(?:COM|NET|ORG|CO|IO|NE)\b(?:/\S*)?", re.I)
STORE_NUM = re.compile(r"[#*]\s?[A-Z0-9]{2,}")
LONG_CODE = re.compile(r"\b[A-Z0-9]*\d[A-Z0-9]{5,}\b")   # e.g. NV7QT4LX1, 57543435804
# Card descriptors end "<MERCHANT> <CITY> <ST>". Rather than an allowlist of
# cities -- which would only ever contain the author's own -- the city is found
# positionally: anchor on a real US state/territory code at the end, then drop
# the token(s) in front of it. Most city names are one token; the multi-word
# ones are enumerated because guessing the token count wrongly would eat part
# of the merchant name.
STATE_CODES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV "
    "WI WY DC PR VI GU AS MP"
).split()
MULTIWORD_CITIES = [
    "NEW YORK", "LOS ANGELES", "SAN ANTONIO", "SAN DIEGO", "SAN FRANCISCO",
    "SAN JOSE", "LAS VEGAS", "NEW ORLEANS", "SALT LAKE CITY", "OKLAHOMA CITY",
    "KANSAS CITY", "ST LOUIS", "SAINT LOUIS", "FORT WORTH", "FORT LAUDERDALE",
    "EL PASO", "LONG BEACH", "VIRGINIA BEACH", "COLORADO SPRINGS", "SANTA FE",
    "SANTA MONICA", "SANTA ANA", "BATON ROUGE", "DES MOINES", "LITTLE ROCK",
    "SIOUX FALLS", "GRAND RAPIDS", "WEST PALM BEACH", "MISSOURI CITY",
    "SUGAR LAND", "JERSEY CITY", "NEW BRUNSWICK", "PALO ALTO", "MENLO PARK",
]
CITY_STATE = re.compile(
    r"\s+(?P<city>[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z][A-Za-z.'\-]*){0,2})"
    r"\s+(?P<state>" + "|".join(STATE_CODES) + r")\s*$"
)
PUNCT_EDGE = re.compile(r"^[\s\-*,.]+|[\s\-*,.]+$")

# Checking rows wrap the merchant in the channel that produced it:
#   "Card Purchase 03/05 Example Cafe TX Card 0000"
CHECKING_PREFIX = re.compile(
    r"^(Recurring )?(Card Purchase( Return)?|Card Purchase With Pin|"
    r"Non-Chase ATM Withdraw|ATM Withdrawal|Payment Sent|Purchase Return)\s+"
    r"(\d{2}/\d{2}\s+)?", re.I,
)
CHECKING_DATE_PREFIX = re.compile(r"^\d{2}/\d{2}\s+")
CHECKING_CARD_SUFFIX = re.compile(r"\s+Card\s+\d{3,4}\s*$", re.I)


# A trailing token that is a company suffix is part of the name, not a city:
# "PROGRESSIVE INS OH" is Progressive, not "Progressive" in the city of Ins.
COMPANY_SUFFIX = {"INS", "LLC", "INC", "CO", "CORP", "LTD", "LP", "PLC", "LLP",
                  "COM", "NET", "ORG", "USA"}


def strip_city_state(s: str) -> str:
    """Drop a trailing ``<CITY> <ST>`` when a real state code ends the string.

    Only the city is removed, never the whole tail. The regex allows up to
    three words before the state, but anything longer than one word must match
    a known multi-word city, otherwise the merchant name gets eaten
    (``EXAMPLE ICE HOUSE SOMETOWN TX`` must keep "EXAMPLE ICE HOUSE").
    """
    hit = CITY_STATE.search(s)
    if not hit:
        return s
    words = hit.group("city").split()
    if len(words) > 1:
        for n in (3, 2):
            if " ".join(words[-n:]).upper().replace(".", "") in MULTIWORD_CITIES:
                return (s[: hit.start()] + " " + " ".join(words[:-n])).rstrip()
    last = words[-1].upper().strip(".")
    # A word that names a *kind of business* is part of the merchant, not a
    # city: "CORNER BAKERY NY", "KOMODO PUB TX", "BEST STOP SUPERMARKET LA".
    # Dropping it would also destroy the signal the category hints run on.
    if last in COMPANY_SUFFIX or any(p.search(last) for p, _ in COMPILED_HINTS):
        return s[: hit.start()] + " " + " ".join(words)      # keep the name, drop the state
    return (s[: hit.start()] + " " + " ".join(words[:-1])).rstrip()


def clean(raw: str) -> str:
    """Strip processor prefixes, store codes, phones, URLs, city and state."""
    # Checking rows read "<CHANNEL> MM/DD <MERCHANT> <ST> Card NNNN" -- no city
    # between merchant and state, so city-stripping must not run on them or it
    # eats the last word of the name.
    s, checking_format = CHECKING_PREFIX.subn("", raw)
    s = CHECKING_DATE_PREFIX.sub("", s)
    s = CHECKING_CARD_SUFFIX.sub("", s)
    s = PROCESSOR_PREFIX.sub("", s)
    s = URL.sub(" ", s)
    s = PHONE.sub(" ", s)
    s = STORE_NUM.sub(" ", s)
    s = LONG_CODE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not checking_format:
        s = strip_city_state(s)
    s = TRAILING_STATE.sub(" ", s)          # a bare state with no city
    s = re.sub(r"\s+", " ", s)
    s = PUNCT_EDGE.sub("", s)
    s = s.strip()
    if s.upper() in STATE_CODES:            # nothing left but a state code
        s = ""

    # Merchants whose name *is* a domain ("NETFLIX.COM NETFLIX.COM CA") get
    # emptied by URL stripping; recover the domain's root label instead.
    if not s:
        hit = re.search(r"([A-Za-z0-9][A-Za-z0-9-]*)\.(?:COM|NET|ORG|CO|IO|NE)\b", raw, re.I)
        if hit:
            s = hit.group(1)
    return s


def titlecase(s: str) -> str:
    """Title-case a cleaned descriptor, leaving short all-caps acronyms alone."""
    out = []
    for word in s.split():
        if len(word) <= 3 and word.isupper():
            out.append(word)
        elif word.isupper() or word.islower():
            out.append(word.capitalize())
        else:
            out.append(word)
    return " ".join(out)


def normalize(description: str, account: str, kind: str) -> tuple[str, str]:
    """Return (merchant, category) for one transaction."""
    raw = description.upper()

    # Kind settles some cases outright, before any name matching.
    if kind == "interest":
        return "Chase card interest", FEES
    if kind == "fee":
        return "Chase card fee", FEES
    if kind == "cash_advance":
        return "Cash advance", CASH
    if kind == "payment" and account == "credit":
        return "Chase card payment", TRANSFERS

    # Inflows are classified on their own terms: a merchant name on money
    # arriving means a refund from them, not spending at them.
    if kind == "deposit":
        return inflow(description)

    hit = p2p(CHECKING_DATE_PREFIX.sub("", description).strip())
    if hit:
        return hit

    # An ACH entry is identified by its originator id before anything else: the
    # id is stable where the descriptor text is not.
    originator = ach_originator(description)
    if originator and originator.upper() in ACH_RULES:
        merchant, category = ACH_RULES[originator.upper()]
        return merchant, (REFUNDS if kind == "credit" else category)

    for pattern, merchant, category in COMPILED:
        if pattern.search(raw):
            # A refund keeps its merchant but is not spending in that category.
            return merchant, (REFUNDS if kind == "credit" else category)

    # Fold the volatile ACH reference block away so one payee stays one
    # merchant across months.
    description = strip_ach_tail(description)
    name = titlecase(clean(description)) or description.strip()
    if kind == "credit":
        return name, REFUNDS
    cleaned = clean(raw)
    for pattern, category in COMPILED_HINTS:
        if pattern.search(cleaned):
            return name, category
    for pattern, category in PROCESSOR_CATEGORY:
        if pattern.match(raw):
            return name, category
    return name, UNCATEGORIZED
