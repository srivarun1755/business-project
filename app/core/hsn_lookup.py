"""
HSN Code Lookup Engine
======================
Provides O(1) HSN code lookup for common grocery and FMCG products
sold by Indian kirana stores, wholesalers, and distributors.

AI is never used for HSN lookup — all mappings are deterministic.
"""

from typing import Optional

# HSN code → (description, GST rate %)
# Source: Central Board of Indirect Taxes and Customs (CBIC) HSN schedule
HSN_RATE_TABLE: dict[str, tuple[str, float]] = {
    # Chapter 10 — Cereals
    "1006": ("Rice", 0.0),
    "100610": ("Rice in husk (paddy or rough)", 0.0),
    "100620": ("Husked (brown) rice", 5.0),
    "100630": ("Semi-milled or wholly milled rice", 5.0),
    "100640": ("Broken rice", 5.0),
    "1001": ("Wheat and meslin", 0.0),
    "100190": ("Other wheat and meslin", 0.0),
    "1002": ("Rye", 0.0),
    "1003": ("Barley", 0.0),
    "1004": ("Oats", 0.0),
    "1005": ("Maize (corn)", 0.0),
    "1007": ("Grain sorghum", 0.0),
    "1008": ("Buckwheat, millet and canary seed", 0.0),
    # Chapter 11 — Milling products
    "1101": ("Wheat or meslin flour", 0.0),
    "110100": ("Wheat or meslin flour", 0.0),
    "1102": ("Cereal flours other than wheat", 5.0),
    "1103": ("Cereal groats, meal and pellets", 0.0),
    "1104": ("Processed cereal grains", 5.0),
    "1106": ("Flour of dried leguminous vegetables", 5.0),
    # Chapter 17 — Sugars
    "1701": ("Cane or beet sugar and chemically pure sucrose", 5.0),
    "170111": ("Raw cane sugar", 5.0),
    "170112": ("Beet sugar", 5.0),
    "170191": ("Refined sugar containing added flavouring or colouring", 5.0),
    "170199": ("Other sugar", 5.0),
    "1702": ("Other sugars, including lactose, maltose, glucose", 18.0),
    "1703": ("Molasses", 28.0),
    # Chapter 15 — Animal or vegetable fats and oils
    "1507": ("Soya-bean oil", 5.0),
    "1508": ("Ground-nut oil", 5.0),
    "1509": ("Olive oil", 5.0),
    "1511": ("Palm oil", 5.0),
    "1512": ("Sunflower-seed, safflower or cotton-seed oil", 5.0),
    "1513": ("Coconut oil, palm kernel oil", 5.0),
    "1514": ("Rapeseed, colza or mustard oil", 5.0),
    "1516": ("Animal or vegetable fats and oils, hydrogenated", 12.0),
    "1517": ("Margarine; edible mixtures of fats", 12.0),
    # Chapter 7 — Vegetables
    "0701": ("Potatoes, fresh or chilled", 0.0),
    "0702": ("Tomatoes, fresh or chilled", 0.0),
    "0703": ("Onions, shallots, garlic, leeks", 0.0),
    "0704": ("Cabbages, cauliflowers", 0.0),
    "0707": ("Cucumbers and gherkins", 0.0),
    "0708": ("Leguminous vegetables, shelled or unshelled", 0.0),
    "0709": ("Other vegetables", 0.0),
    "0710": ("Vegetables, frozen", 5.0),
    # Chapter 8 — Fruits
    "0801": ("Coconuts, Brazil nuts, cashew nuts", 12.0),
    "0802": ("Other nuts", 12.0),
    "0803": ("Bananas", 0.0),
    "0804": ("Dates, figs, pineapples, avocados, guavas, mangoes", 0.0),
    "0805": ("Citrus fruit", 0.0),
    "0806": ("Grapes", 0.0),
    "0807": ("Melons and papaws", 0.0),
    "0808": ("Apples, pears and quinces", 0.0),
    # Chapter 9 — Coffee, tea, spices
    "0901": ("Coffee", 5.0),
    "0902": ("Tea", 5.0),
    "0904": ("Pepper", 5.0),
    "0905": ("Vanilla", 5.0),
    "0906": ("Cinnamon and cinnamon-tree flowers", 5.0),
    "0907": ("Cloves", 5.0),
    "0908": ("Nutmeg, mace and cardamoms", 5.0),
    "0909": ("Seeds of anise, badian, fennel", 5.0),
    "0910": ("Ginger, saffron, turmeric (curcuma)", 5.0),
    # Chapter 4 — Dairy
    "0401": ("Milk and cream, not concentrated", 0.0),
    "0402": ("Milk and cream, concentrated or sweetened", 5.0),
    "0403": ("Buttermilk, curdled milk, yogurt", 5.0),
    "0404": ("Whey", 5.0),
    "0405": ("Butter and other fats of milk", 12.0),
    "0406": ("Cheese and curd", 12.0),
    # Chapter 19 — Preparations of cereals
    "1901": ("Malt extract; food preparations of flour", 18.0),
    "1902": ("Pasta", 12.0),
    "1904": ("Prepared foods obtained by the swelling of cereal", 18.0),
    "1905": ("Bread, pastry, cakes, biscuits", 18.0),
    # Chapter 20 — Preparations of vegetables
    "2001": ("Vegetables, fruit, nuts, preserved by vinegar", 12.0),
    "2002": ("Tomatoes prepared or preserved otherwise", 12.0),
    "2003": ("Mushrooms preserved", 12.0),
    "2004": ("Other vegetables prepared or preserved", 12.0),
    "2005": ("Other vegetables prepared without vinegar", 12.0),
    # Chapter 21 — Miscellaneous edible preparations
    "2101": ("Extracts, essences and concentrates of coffee, tea", 18.0),
    "2103": ("Sauces and preparations; mixed condiments", 12.0),
    "2104": ("Soups and broths", 18.0),
    "2106": ("Food preparations not elsewhere specified", 18.0),
    # Chapter 22 — Beverages
    "2201": ("Waters, ice and snow", 18.0),
    "2202": ("Waters, flavoured or sweetened", 12.0),
    "2203": ("Beer made from malt", 28.0),
    # Chapter 24 — Tobacco
    "2401": ("Unmanufactured tobacco", 28.0),
    "2402": ("Cigars, cheroots, cigarillos and cigarettes", 28.0),
    # Chapter 34 — Soap, detergents
    "3401": ("Soap, organic surface-active products", 18.0),
    "3402": ("Organic surface-active agents", 18.0),
    "3405": ("Polishes and creams for footwear, furniture", 18.0),
    "3406": ("Candles, tapers and the like", 12.0),
    # Chapter 30 — Pharmaceutical products
    "3004": ("Medicaments (excluding goods of heading 30.02)", 12.0),
    # Chapter 33 — Essential oils and cosmetics
    "3301": ("Essential oils", 18.0),
    "3305": ("Preparations for use on the hair", 18.0),
    "3306": ("Preparations for oral or dental hygiene", 18.0),
    "3307": ("Pre-shave, shaving or after-shave preparations", 18.0),
    # Chapter 48 — Paper and paperboard
    "4818": ("Toilet paper and similar paper", 18.0),
    "4819": ("Cartons, boxes, cases, bags of paper", 18.0),
    # Chapter 63 — Other textiles
    "6305": ("Sacks and bags for packing", 12.0),
}

# Product keyword → HSN code (case-insensitive, O(1) lookup)
PRODUCT_HSN_MAP: dict[str, str] = {
    # Rice varieties
    "rice": "1006",
    "basmati": "100630",
    "basmati rice": "100630",
    "sona masoori": "100630",
    "parboiled rice": "100630",
    "broken rice": "100640",
    "brown rice": "100620",
    "paddy": "100610",
    # Wheat & flour
    "wheat": "1001",
    "atta": "1101",
    "wheat flour": "1101",
    "maida": "1101",
    "suji": "1103",
    "sooji": "1103",
    "semolina": "1103",
    "ravva": "1103",
    "rawa": "1103",
    "besan": "1106",
    "gram flour": "1106",
    "sattu": "1106",
    "maize": "1005",
    "corn": "1005",
    "makka": "1005",
    "makki": "1005",
    "barley": "1003",
    "jau": "1003",
    "oats": "1004",
    # Sugar
    "sugar": "1701",
    "chini": "1701",
    "shakkar": "1701",
    "gur": "1702",
    "jaggery": "1702",
    "khandsari": "1701",
    "bura sugar": "1701",
    "powdered sugar": "1701",
    "caster sugar": "1701",
    "molasses": "1703",
    # Oils
    "mustard oil": "1514",
    "sarson oil": "1514",
    "sarson ka tel": "1514",
    "sunflower oil": "1512",
    "soybean oil": "1507",
    "soya oil": "1507",
    "groundnut oil": "1508",
    "moongfali oil": "1508",
    "palm oil": "1511",
    "coconut oil": "1513",
    "nariyal tel": "1513",
    "rice bran oil": "1512",
    "vanaspati": "1516",
    "dalda": "1516",
    "ghee": "0405",
    "desi ghee": "0405",
    "butter": "0405",
    # Pulses / dal
    "dal": "0708",
    "daal": "0708",
    "lentils": "0708",
    "toor dal": "0708",
    "arhar dal": "0708",
    "moong dal": "0708",
    "urad dal": "0708",
    "chana dal": "0708",
    "masoor dal": "0708",
    "kabuli chana": "0708",
    "rajma": "0708",
    "kidney beans": "0708",
    "black eye peas": "0708",
    "lobia": "0708",
    "moth dal": "0708",
    "peas": "0708",
    "matar": "0708",
    # Spices
    "salt": "2501",
    "namak": "2501",
    "pepper": "0904",
    "kali mirch": "0904",
    "red chilli": "0904",
    "lal mirch": "0904",
    "turmeric": "0910",
    "haldi": "0910",
    "coriander": "0909",
    "dhania": "0909",
    "cumin": "0909",
    "jeera": "0909",
    "mustard seeds": "0909",
    "rai": "0909",
    "fenugreek": "0909",
    "methi": "0909",
    "garam masala": "0910",
    "curry powder": "0910",
    "cardamom": "0908",
    "elaichi": "0908",
    "cloves": "0907",
    "laung": "0907",
    "cinnamon": "0906",
    "dalchini": "0906",
    "bay leaf": "0910",
    "tej patta": "0910",
    "ginger": "0910",
    "adrak": "0910",
    "dry ginger": "0910",
    "sonth": "0910",
    "saffron": "0910",
    "kesar": "0910",
    "asafoetida": "0910",
    "hing": "0910",
    "ajwain": "0909",
    "carom seeds": "0909",
    "fennel": "0909",
    "saunf": "0909",
    # Tea & coffee
    "tea": "0902",
    "chai": "0902",
    "chai patti": "0902",
    "green tea": "0902",
    "coffee": "0901",
    "instant coffee": "2101",
    # Milk & dairy
    "milk": "0401",
    "doodh": "0401",
    "curd": "0403",
    "dahi": "0403",
    "yogurt": "0403",
    "buttermilk": "0403",
    "chaas": "0403",
    "lassi": "0403",
    "paneer": "0406",
    "cheese": "0406",
    "cream": "0401",
    "condensed milk": "0402",
    "milk powder": "0402",
    "khoya": "0402",
    "mawa": "0402",
    # Vegetables
    "potato": "0701",
    "aloo": "0701",
    "tomato": "0702",
    "tamatar": "0702",
    "onion": "0703",
    "pyaaz": "0703",
    "garlic": "0703",
    "lahsun": "0703",
    "ginger fresh": "0709",
    "cabbage": "0704",
    "patta gobhi": "0704",
    "cauliflower": "0704",
    "phool gobhi": "0704",
    "brinjal": "0709",
    "baingan": "0709",
    "spinach": "0709",
    "palak": "0709",
    "okra": "0709",
    "bhindi": "0709",
    "cucumber": "0707",
    "kheera": "0707",
    "bitter gourd": "0709",
    "karela": "0709",
    "bottle gourd": "0709",
    "lauki": "0709",
    # Fruits
    "banana": "0803",
    "kela": "0803",
    "mango": "0804",
    "aam": "0804",
    "apple": "0808",
    "seb": "0808",
    "orange": "0805",
    "santra": "0805",
    "grapes": "0806",
    "angoor": "0806",
    "coconut": "0801",
    "nariyal": "0801",
    "cashew": "0801",
    "kaju": "0801",
    "almond": "0802",
    "badam": "0802",
    "walnut": "0802",
    "akhrot": "0802",
    "peanut": "0801",
    "moongfali": "0801",
    "groundnut": "0801",
    "raisin": "0806",
    "kishmish": "0806",
    # Packaged foods
    "biscuit": "1905",
    "bread": "1905",
    "cake": "1905",
    "cookies": "1905",
    "noodles": "1902",
    "pasta": "1902",
    "macaroni": "1902",
    "vermicelli": "1902",
    "seviyan": "1902",
    "cornflakes": "1904",
    "poha": "1104",
    "chivda": "1904",
    "namkeen": "1904",
    "chips": "2005",
    "papad": "1905",
    "pickle": "2001",
    "achaar": "2001",
    "jam": "2007",
    "sauce": "2103",
    "ketchup": "2103",
    "vinegar": "2209",
    "soy sauce": "2103",
    # Beverages
    "water": "2201",
    "mineral water": "2201",
    "cold drink": "2202",
    "soft drink": "2202",
    "juice": "2009",
    # Household
    "soap": "3401",
    "sabun": "3401",
    "detergent": "3402",
    "washing powder": "3402",
    "surf": "3402",
    "ariel": "3402",
    "tide": "3402",
    "toothpaste": "3306",
    "toothbrush": "3306",
    "shampoo": "3305",
    "hair oil": "3305",
    "tel": "3305",
    "mosquito coil": "3808",
    "agarbatti": "3307",
    "incense sticks": "3307",
    "candle": "3406",
    "diya": "3406",
    "match": "3605",
    "matchbox": "3605",
    # Packaging
    "bag": "6305",
    "bora": "6305",
    "gunny bag": "6305",
    "sack": "6305",
    "box": "4819",
    "carton": "4819",
    "packet": "4819",
    "polybag": "3923",
    "tissue": "4818",
    "toilet paper": "4818",
}

# Build inverted phonetic map at module load time (populated by HSNLookup engine)
_PHONETIC_CACHE: dict[str, str] = {}


def get_hsn_for_product(product_name: str) -> Optional[str]:
    """
    O(1) HSN code lookup by normalised product name.
    Returns the HSN code string, or None if not found.
    """
    key = product_name.strip().lower()
    return PRODUCT_HSN_MAP.get(key)


def get_gst_rate(hsn_code: str) -> float:
    """Return GST rate (%) for the given HSN code. Returns 0.0 if not found."""
    entry = HSN_RATE_TABLE.get(hsn_code)
    if entry:
        return entry[1]
    # Try parent chapter (first 4 digits)
    chapter4 = hsn_code[:4]
    entry = HSN_RATE_TABLE.get(chapter4)
    if entry:
        return entry[1]
    # Try chapter (first 2 digits)
    chapter2 = hsn_code[:2]
    entry = HSN_RATE_TABLE.get(chapter2)
    return entry[1] if entry else 0.0


def get_hsn_description(hsn_code: str) -> str:
    """Return human-readable description for HSN code."""
    entry = HSN_RATE_TABLE.get(hsn_code)
    if entry:
        return entry[0]
    chapter4 = hsn_code[:4]
    entry = HSN_RATE_TABLE.get(chapter4)
    if entry:
        return entry[0]
    return "Goods"
