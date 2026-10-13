"""Built-in domain knowledge used by the deterministic rules.

Everything here is a default. Project-level synonyms (human approved) always
take precedence, and projects can extend these lists via project.settings.
"""
from __future__ import annotations

# Modifiers that do not change the product type ("ssd推薦" == "ssd").
GENERIC_MODIFIERS = {
    "推薦", "便宜", "優惠", "特價", "熱銷", "人氣", "排行", "排行榜", "比較", "評價", "開箱",
    "價格", "價錢", "哪裡買", "官方", "正品", "現貨", "全新", "專用", "系列", "類", "商品",
    "用品", "產品", "品牌", "款", "電腦", "pc", "用", "best", "cheap", "sale", "price",
    "review", "top", "new", "the", "for", "of", "and", "with",
}

KNOWN_BRANDS = {
    "asus", "acer", "apple", "samsung", "sandisk", "kingston", "transcend", "adata", "wd",
    "seagate", "logitech", "logi", "razer", "msi", "lenovo", "hp", "dell", "sony", "lg",
    "xiaomi", "小米", "華碩", "宏碁", "蘋果", "三星", "金士頓", "創見", "威剛", "羅技",
    "tp-link", "tplink", "d-link", "dlink", "netgear", "mercusys", "tenda", "zyxel",
    "nintendo", "任天堂", "gigabyte", "技嘉", "微星", "nvidia", "amd", "intel", "anker",
    "belkin", "ugreen", "綠聯", "baseus", "倍思", "jbl", "bose", "edifier", "漫步者",
    "crucial", "micron", "lexar", "pny", "toshiba", "synology", "qnap", "garmin",
}

# Words that indicate a temporary / campaign intent rather than a stable category.
TEMPORARY_INTENT = {
    "活動", "限時", "特賣", "促銷", "折扣", "母親節", "父親節", "情人節", "聖誕", "雙11", "雙十一",
    "雙12", "618", "週年慶", "周年慶", "新年", "過年", "年貨", "福袋", "清倉", "出清", "團購",
    "black friday", "sale", "deal", "deals", "clearance", "campaign", "promo", "event",
}

# Labels that are typically "grouping" nodes, not product types. A child under a
# grouping node is fine even with no lexical overlap.
GROUP_LABEL_HINTS = (
    "/", "周邊", "週邊", "配件", "裝置", "設備", "用品", "產品", "家電", "3c", "專區", "系列",
    "類", "館", "其他", "生活", "電子", "電腦", "數位", "影音", "網通", "accessories",
    "peripherals", "devices", "electronics", "products", "&",
)

# Levels that add no taxonomy meaning when they appear mid-breadcrumb.
GENERIC_LEVEL_LABELS = {
    "全部", "全部商品", "所有商品", "所有分類", "全部分類", "其他", "其它", "更多", "熱門", "推薦",
    "熱門商品", "精選", "商品分類", "分類", "category", "categories", "all", "all products",
    "more", "others", "other", "shop all",
}

HOME_LABEL_HINTS = ("首頁", "home", "主頁", "首页", "購物網", "24h購物", "商城")

# Ambiguous product heads -> sense name -> context words.
# If an SRP's context belongs to one sense and the candidate category's
# breadcrumb belongs to another, the candidate is "clearly wrong branch" (-100).
BRANCH_CONFLICTS: dict[str, dict[str, set[str]]] = {
    "switch": {
        "networking": {"poe", "port", "gigabit", "網路", "交換器", "交換機", "hub", "managed", "lan",
                        "ethernet", "網通", "路由", "router", "千兆", "埠", "網管"},
        "gaming": {"nintendo", "任天堂", "ns", "joy-con", "joycon", "遊戲", "電玩", "主機", "oled", "lite",
                   "game", "gaming", "amiibo"},
    },
    "mouse": {
        "computer": {"無線", "wireless", "電競", "藍牙", "滑鼠", "電腦", "gaming", "usb", "optical"},
        "pet": {"寵物", "老鼠", "捕鼠", "pet", "cat", "trap", "貓"},
    },
    "充電器": {
        "laptop": {"筆電", "筆記型電腦", "laptop", "notebook", "macbook"},
        "phone": {"手機", "iphone", "phone", "android", "快充頭"},
        "vehicle": {"車用", "車充", "汽車", "car"},
    },
    "電池": {
        "laptop": {"筆電", "筆記型電腦", "laptop", "notebook"},
        "household": {"3號", "4號", "鹼性", "aa", "aaa", "充電電池", "鈕扣"},
        "vehicle": {"汽車", "機車", "電瓶"},
    },
    "記憶體": {
        "ram": {"ddr4", "ddr5", "ddr3", "ram", "dimm", "so-dimm", "桌機", "筆電記憶體"},
        "storage": {"記憶卡", "sd", "microsd", "隨身碟", "card"},
    },
    "螢幕": {
        "monitor": {"電腦", "電競", "顯示器", "monitor", "曲面", "4k", "144hz"},
        "protector": {"保護貼", "玻璃貼", "膜", "protector"},
    },
}

# Seeded default synonyms (source=DEFAULT; editable/deletable per project).
DEFAULT_SYNONYMS: list[tuple[str, str]] = [
    ("筆電", "筆記型電腦"),
    ("laptop", "筆記型電腦"),
    ("notebook", "筆記型電腦"),
    ("wifi分享器", "無線路由器"),
    ("wifi router", "無線路由器"),
    ("無線分享器", "無線路由器"),
    ("router", "無線路由器"),
    ("路由器", "無線路由器"),
    ("poe switch", "網路交換器"),
    ("network switch", "網路交換器"),
    ("交換器", "網路交換器"),
    ("hub交換器", "網路交換器"),
    ("網通", "網路"),
    ("mouse", "滑鼠"),
    ("keyboard", "鍵盤"),
    ("ssd", "固態硬碟"),
    ("hdd", "傳統硬碟"),
    ("隨身硬碟", "外接硬碟"),
    ("行動硬碟", "外接硬碟"),
    ("sd卡", "記憶卡"),
    ("tf卡", "microsd"),
    ("memory card", "記憶卡"),
    ("card reader", "讀卡機"),
    ("usb hub", "usb集線器"),
    ("集線器", "usb集線器"),
    ("顯卡", "顯示卡"),
    ("gpu", "顯示卡"),
    ("graphics card", "顯示卡"),
    ("motherboard", "主機板"),
    ("電腦喇叭", "pc用喇叭"),
    ("耳麥", "耳機麥克風"),
    ("webcam", "網路攝影機"),
    ("視訊鏡頭", "網路攝影機"),
    ("adapter", "變壓器"),
]

# Minimal EN glossary for deterministic translation of common taxonomy labels.
# Used before the LLM; anything not covered is left for AI or marked MISSING.
EN_GLOSSARY: dict[str, str] = {
    "酷澎首頁": "Coupang Home",
    "首頁": "Home",
    "電腦3c": "Computers & Electronics",
    "電腦/平板周邊": "Computer & Tablet Accessories",
    "電腦配件": "Computer Accessories",
    "儲存裝置": "Storage Devices",
    "記憶卡": "Memory Cards",
    "讀卡機": "Card Readers",
    "變壓器": "Power Adapters",
    "網路/分享器": "Networking & Routers",
    "無線路由器": "Wireless Routers",
    "網路交換器": "Network Switches",
    "筆記型電腦": "Laptops",
    "筆電": "Laptops",
    "筆電配件": "Laptop Accessories",
    "筆電充電器": "Laptop Chargers",
    "筆電電池": "Laptop Batteries",
    "筆電包": "Laptop Bags",
    "滑鼠": "Mice",
    "無線滑鼠": "Wireless Mice",
    "電競滑鼠": "Gaming Mice",
    "鍵盤": "Keyboards",
    "顯示卡": "Graphics Cards",
    "主機板": "Motherboards",
    "顯示卡/主機板": "Graphics Cards & Motherboards",
    "固態硬碟": "Solid State Drives",
    "外接硬碟": "External Hard Drives",
    "隨身碟": "USB Flash Drives",
    "喇叭": "Speakers",
    "pc用喇叭": "PC Speakers",
    "耳機": "Headphones",
    "藍牙耳機": "Bluetooth Earphones",
    "螢幕": "Monitors",
    "電競螢幕": "Gaming Monitors",
    "網路攝影機": "Webcams",
    "usb集線器": "USB Hubs",
    "電玩": "Video Games",
    "電玩主機": "Game Consoles",
    "平板": "Tablets",
    "平板電腦": "Tablets",
    "手機": "Mobile Phones",
    "手機配件": "Phone Accessories",
    "充電器": "Chargers",
    "傳輸線": "Cables",
    "電腦零組件": "Computer Components",
    "記憶體": "Memory (RAM)",
    "電源供應器": "Power Supplies",
    "機殼": "PC Cases",
    "散熱器": "Coolers",
    "網路設備": "Networking Equipment",
    "網通設備": "Networking Equipment",
    "儲存設備": "Storage Devices",
    "電腦周邊": "Computer Peripherals",
    "筆電支架": "Laptop Stands",
    "筆電散熱墊": "Laptop Cooling Pads",
    "散熱墊": "Cooling Pads",
    "機械鍵盤": "Mechanical Keyboards",
    "poe交換器": "PoE Switches",
    "mesh wifi": "Mesh WiFi Systems",
    "印表機": "Printers",
}

# Words that only say "this is a group of things" (網路設備 ≈ 網路/分享器 ≈ 網通設備).
GROUP_SUFFIXES = ("設備", "裝置", "周邊", "配件", "產品", "用品", "器材", "專區", "系列", "商品", "週邊", "館", "類", "3c")

# Deterministic EN for common SRP modifiers (brands, attributes). Used to build
# "<modifiers> <category EN>" names before falling back to AI.
MODIFIER_EN: dict[str, str] = {
    "三星": "Samsung", "羅技": "Logitech", "華碩": "ASUS", "宏碁": "Acer", "蘋果": "Apple", "小米": "Xiaomi",
    "金士頓": "Kingston", "創見": "Transcend", "威剛": "ADATA", "技嘉": "Gigabyte", "微星": "MSI", "任天堂": "Nintendo",
    "綠聯": "UGREEN", "倍思": "Baseus", "漫步者": "Edifier",
    "無線": "Wireless", "藍牙": "Bluetooth", "電競": "Gaming", "機械": "Mechanical", "降噪": "Noise-Cancelling",
    "靜音": "Silent", "人體工學": "Ergonomic", "迷你": "Mini", "攜帶型": "Portable", "便攜": "Portable",
    "外接": "External", "高速": "High-Speed", "快充": "Fast-Charging", "防水": "Waterproof", "曲面": "Curved",
    "手機": "Phone", "筆電": "Laptop", "平板": "Tablet", "電腦": "Computer", "車用": "Car",
}
BRAND_CASE: dict[str, str] = {
    "asus": "ASUS", "acer": "Acer", "apple": "Apple", "samsung": "Samsung", "sandisk": "SanDisk", "kingston": "Kingston",
    "logitech": "Logitech", "razer": "Razer", "msi": "MSI", "lenovo": "Lenovo", "hp": "HP", "dell": "Dell", "sony": "Sony",
    "lg": "LG", "tp-link": "TP-Link", "tplink": "TP-Link", "d-link": "D-Link", "netgear": "NETGEAR", "wd": "WD",
    "seagate": "Seagate", "adata": "ADATA", "transcend": "Transcend", "nintendo": "Nintendo", "gigabyte": "Gigabyte",
    "anker": "Anker", "jbl": "JBL", "bose": "Bose", "crucial": "Crucial", "lexar": "Lexar", "rtx": "RTX", "ddr5": "DDR5",
    "ddr4": "DDR4", "oled": "OLED", "usb": "USB", "type-c": "Type-C", "mesh": "Mesh", "poe": "PoE", "wifi": "WiFi",
}
