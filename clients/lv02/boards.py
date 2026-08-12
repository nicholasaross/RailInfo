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
    "width": 320, "height": 170,       # LANDSCAPE (driver transposes 90deg onto the portrait glass)
    "rotation": 0xC0,                  # physical-panel MADCTL (MX|MY); transpose does the rotation
    "xoff": 35, "yoff": 0,
    "swap": False,
    "landscape": True,                 # rotate 90deg in the driver (ST7789 RAMWR is column-fast)
    "coloff": 34, "glassw": 170,       # 170-wide glass at physical columns 34..203 (was 35: shifted
                                       # the image up 1px, top row wrapped to the bottom)
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
        xoff=b["xoff"], yoff=b["yoff"], swap=b["swap"],
        landscape=b["landscape"], coloff=b["coloff"], glassw=b["glassw"],
        inversion=b["inversion"],
    )
    return display, b
