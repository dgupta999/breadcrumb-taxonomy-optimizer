"""Generates sample taxonomy / SRP files (CSV + XLSX) that exercise every rule.

Run:  backend/.venv/Scripts/python sample_data/make_samples.py
"""
import csv
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent
H = "酷澎首頁"
HE = "Coupang Home"
C3 = f"{H} > 電腦3C"
C3E = f"{HE} > Computers & Electronics"
PERI = f"{C3} > 電腦/平板周邊"
PERIE = f"{C3E} > Computer & Tablet Accessories"
ACC = f"{PERI} > 電腦配件"
ACCE = f"{PERIE} > Computer Accessories"
STO = f"{PERI} > 儲存裝置"
STOE = f"{PERIE} > Storage Devices"

# id, name_cn, name_en, breadcrumb_cn (incl. self), breadcrumb_en, products
TAXONOMY = [
    (100, "電腦3C", "Computers & Electronics", C3, C3E, 52000),
    (110, "電腦/平板周邊", "Computer & Tablet Accessories", PERI, PERIE, 18000),
    (120, "儲存裝置", "Storage Devices", STO, STOE, 4200),
    (121, "記憶卡", "Memory Cards", f"{STO} > 記憶卡", f"{STOE} > Memory Cards", 900),
    (122, "microSD", "microSD Cards", f"{STO} > 記憶卡 > microSD", f"{STOE} > Memory Cards > microSD Cards", 520),
    (123, "SSD", "SSD", f"{STO} > SSD", f"{STOE} > SSD", 760),
    (124, "外接硬碟", "External Hard Drives", f"{STO} > 外接硬碟", f"{STOE} > External Hard Drives", 410),
    (125, "隨身碟", "USB Flash Drives", f"{STO} > 隨身碟", f"{STOE} > USB Flash Drives", 640),
    (126, "讀卡機", "Card Readers", f"{STO} > 讀卡機", f"{STOE} > Card Readers", 210),
    (127, "讀卡機", "Card Readers", f"{STO} > 讀卡機 > 讀卡機", f"{STOE} > Card Readers > Card Readers", 35),
    (128, "變壓器", "Power Adapters", f"{STO} > 讀卡機 > 變壓器", f"{STOE} > Card Readers > Power Adapters", 330),
    (130, "電腦配件", "Computer Accessories", ACC, ACCE, 6100),
    (131, "網路/分享器", "Networking & Routers", f"{ACC} > 網路/分享器", f"{ACCE} > Networking & Routers", 880),
    (132, "滑鼠", "Mice", f"{ACC} > 滑鼠", f"{ACCE} > Mice", 1500),
    (133, "鍵盤", "Keyboards", f"{ACC} > 鍵盤", f"{ACCE} > Keyboards", 1300),
    (134, "PC 用喇叭", "PC Speakers", f"{ACC} > PC 用喇叭", f"{ACCE} > PC Speakers", 260),
    (135, "網路攝影機", "Webcams", f"{ACC} > 網路攝影機", f"{ACCE} > Webcams", 190),
    (136, "USB集線器", "USB Hubs", f"{ACC} > USB集線器", f"{ACCE} > USB Hubs", 340),
    (137, "隨身碟", "USB Flash Drives", f"{ACC} > 隨身碟", f"{ACCE} > USB Flash Drives", 120),
    (138, "散熱墊", "Cooling Pads", f"{ACC} > 散熱墊", "", 95),
    (111, "無線滑鼠", "Wireless Mice", f"{PERI} > 無線滑鼠", f"{PERIE} > Wireless Mice", 610),
    (112, "筆電充電器", "Laptop Chargers", f"{PERI} > 筆電充電器", f"{PERIE} > Laptop Chargers", 450),
    (113, "筆電電池", "Laptop Batteries", f"{PERI} > 筆電電池", f"{PERIE} > Laptop Batteries", 230),
    (114, "筆電包", "", f"{PERI} > 筆電包", "", 380),
    (200, "筆記型電腦", "Laptops", f"{C3} > 筆記型電腦", f"{C3E} > Laptops", 2100),
    (201, "電競筆電", "Gaming Laptops", f"{C3} > 筆記型電腦 > 電競筆電", f"{C3E} > Laptops > Gaming Laptops", 400),
    (210, "平板電腦", "Tablets", f"{C3} > 平板電腦", f"{C3E} > Tablets", 900),
    (220, "螢幕", "Monitors", f"{C3} > 螢幕", f"{C3E} > Monitors", 800),
    (221, "電競螢幕", "Gaming Monitors", f"{C3} > 螢幕 > 電競螢幕", f"{C3E} > Monitors > Gaming Monitors", 260),
    (230, "電玩", "Video Games", f"{C3} > 電玩", f"{C3E} > Video Games", 3000),
    (231, "Nintendo Switch", "Nintendo Switch", f"{C3} > 電玩 > Nintendo Switch", f"{C3E} > Video Games > Nintendo Switch", 700),
    (232, "PS5", "PS5", f"{C3} > 電玩 > PS5", f"{C3E} > Video Games > PS5", 500),
    (240, "耳機", "Headphones", f"{C3} > 耳機", f"{C3E} > Headphones", 2400),
    (241, "藍牙耳機", "Bluetooth Earphones", f"{C3} > 耳機 > 藍牙耳機", f"{C3E} > Headphones > Bluetooth Earphones", 1200),
    (250, "手機", "Mobile Phones", f"{C3} > 手機", f"{C3E} > Mobile Phones", 1800),
    (251, "手機配件", "Phone Accessories", f"{C3} > 手機 > 手機配件", f"{C3E} > Mobile Phones > Phone Accessories", 5200),
    (252, "充電器", "Chargers", f"{C3} > 手機 > 手機配件 > 充電器", f"{C3E} > Mobile Phones > Phone Accessories > Chargers", 900),
    (260, "印表機", "Printers", f"{C3} > 全部商品 > 印表機", f"{C3E} > All Products > Printers", 300),
]

# keyword, h1, english, volume, products
SRPS = [
    ("128g記憶卡", "128g記憶卡", "", 2900, 140),
    ("256gb microsd", "256GB microSD", "256GB microSD", 3600, 90),
    ("sandisk記憶卡", "SanDisk記憶卡", "", 1900, 80),
    ("記憶卡", "記憶卡", "memory card", 12000, 900),
    ("ssd", "SSD", "ssd", 33000, 760),
    ("ssd推薦", "SSD推薦", "", 5400, 700),
    ("1tb ssd", "1TB SSD", "1TB SSD", 6600, 210),
    ("三星 ssd", "三星 SSD", "", 2400, 60),
    ("外接硬碟 2tb", "外接硬碟 2TB", "", 1300, 70),
    ("asus筆電", "ASUS筆電", "ASUS laptop", 8100, 160),
    ("電競筆電", "電競筆電", "gaming laptop", 9900, 400),
    ("筆電充電器", "筆電充電器", "", 4400, 450),
    ("asus 筆電充電器", "ASUS 筆電充電器", "", 880, 40),
    ("hp 筆電電池", "HP 筆電電池", "", 590, 25),
    ("無線滑鼠", "無線滑鼠", "wireless mouse", 6600, 610),
    ("羅技滑鼠", "羅技滑鼠", "", 5400, 120),
    ("電競滑鼠", "電競滑鼠", "", 4400, 230),
    ("電競滑鼠 無線", "無線電競滑鼠", "", 1000, 90),
    ("機械鍵盤", "機械鍵盤", "", 6600, 300),
    ("藍牙鍵盤", "藍牙鍵盤", "", 2900, 150),
    ("電腦喇叭", "電腦喇叭", "", 2400, 180),
    ("poe switch", "PoE Switch", "PoE switch", 1600, 45),
    ("網路交換器", "網路交換器", "", 2900, 120),
    ("8port 交換器", "8 Port 交換器", "", 480, 30),
    ("wifi分享器", "WiFi分享器", "", 14800, 260),
    ("mesh wifi", "Mesh WiFi", "mesh wifi", 3600, 70),
    ("tp-link 路由器", "TP-Link 路由器", "", 2400, 90),
    ("無線路由器", "無線路由器", "wireless router", 5400, 240),
    ("顯示卡", "顯示卡", "graphics card", 22200, 0),
    ("rtx 4060 顯示卡", "RTX 4060 顯示卡", "", 6600, 0),
    ("顯卡", "顯卡", "", 9900, 0),
    ("主機板", "主機板", "motherboard", 8100, 0),
    ("讀卡機", "讀卡機", "card reader", 3600, 210),
    ("usb hub", "USB Hub", "usb hub", 2900, 340),
    ("type-c hub", "Type-C Hub", "", 1900, 110),
    ("switch 遊戲", "Switch 遊戲", "switch games", 12100, 500),
    ("switch oled", "Switch OLED", "switch oled", 8100, 40),
    ("藍牙耳機", "藍牙耳機", "bluetooth earphones", 27100, 1200),
    ("降噪耳機", "降噪耳機", "", 6600, 300),
    ("27吋 電競螢幕", "27吋 電競螢幕", "", 1900, 80),
    ("視訊鏡頭", "視訊鏡頭", "", 1600, 140),
    ("筆電散熱墊", "筆電散熱墊", "", 1300, 60),
    ("筆電支架", "筆電支架", "", 3600, 150),
    ("母親節禮物 3c", "母親節禮物 3C", "", 1000, 0),
    ("手機充電器", "手機充電器", "", 4400, 600),
    ("ddr5 記憶體", "DDR5 記憶體", "DDR5 RAM", 2900, 0),
    ("筆電包 15吋", "筆電包 15吋", "", 1000, 120),
    ("變壓器", "變壓器", "", 2400, 330),
]


def write(name, headers, rows):
    with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    wb.save(OUT / f"{name}.xlsx")


write(
    "current_taxonomy",
    ["Category ID", "Category URL", "Category Name CN", "Category Name EN", "Breadcrumb CN", "Breadcrumb EN", "Product Count", "Status"],
    [(i, f"https://www.tw.coupang.com/categories/{i}", cn, en, bc, be, pc, "active") for i, cn, en, bc, be, pc in TAXONOMY],
)
write(
    "srp_data",
    ["SRP Keyword", "SRP URL", "H1", "English Keyword", "Search Volume", "Product Count"],
    [(k, f"https://www.tw.coupang.com/search?q={k.replace(' ', '+')}", h1, en, v, p) for k, h1, en, v, p in SRPS],
)
print("wrote", len(TAXONOMY), "categories and", len(SRPS), "SRPs")
