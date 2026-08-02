# boards.py - Hardware definition for the Luckyminer LV02 (LilyGo T-Display-S3 clone).
#
# ESP32-S3 (16MB flash, NO PSRAM) + 1.9" 170x320 ST7789 on an 8-bit PARALLEL (i8080) bus - NOT SPI.
# Verified pinout (matches the LilyGo T-Display-S3; power/backlight confirmed empirically, the rest
# validated by an on-panel init + colour fill - see setup_log.md):
#   POWER_ON=15  BL=38  CS=6  DC=7  RST=5  WR=8  RD=9
#   data D0..D7 = 39,40,41,42,45,46,47,48   (GPIO43/44 are UART0, skipped)
#   Buttons: BOOT=GPIO0, KEY=GPIO14 (two front buttons; the side button is Reset).
#
# The client reuses cfg["button"] (a single BOOT-style button) + cfg["touch"]=None, so the NM-TV
# railinfo_client.py runs here unchanged; only this file and the parallel st7789.py differ.

from st7789 import ST7789

LV02 = {
    "power": 15, "bl": 38, "cs": 6, "dc": 7, "rst": 5, "wr": 8, "rd": 9,
    "data": (39, 40, 41, 42, 45, 46, 47, 48),
    "width": 170, "height": 320,       # NATIVE PORTRAIT (no MV transpose -> correct data order)
    "rotation": 0xC0,                  # MADCTL MX|MY (un-mirror X + flip Y -> upright, readable)
    "xoff": 35, "yoff": 0,             # 170-wide glass sits at controller columns 35..204
    "swap": False,                     # portrait: x->CASET, y->RASET directly
    "inversion": True,                 # IPS -> INVON for normal colours
    "button": 0,                       # BOOT (GPIO0) cycles views
    "touch": None,                     # no capacitive pad on this board
}


def init_display():
    b = LV02
    display = ST7789(
        power=b["power"], bl=b["bl"], cs=b["cs"], dc=b["dc"], rst=b["rst"],
        wr=b["wr"], rd=b["rd"], data=b["data"],
        width=b["width"], height=b["height"], rotation=b["rotation"],
        xoff=b["xoff"], yoff=b["yoff"], swap=b["swap"], inversion=b["inversion"],
    )
    return display, b
