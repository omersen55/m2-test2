"""
Yeni metin türü ekleme aracı.

Kullanım:
    python sablon_al.py              -> 3 sn sonra ekran görüntüsü alır
    python sablon_al.py resim.png    -> verilen resimden seçim yapar

Açılan pencerede metnin üstündeki İSİM YAZISINI (örn. "Ruh Metni") fareyle
sıkıca çevrele, ENTER'a bas. Bitince ESC. Sonra konsolda dosyaya bir ad ver.
"""
import os
import sys
import time

import cv2
import mss
import numpy as np

KLASOR = os.path.join("templates", "isim")
os.makedirs(KLASOR, exist_ok=True)

if len(sys.argv) > 1:
    img = cv2.imread(sys.argv[1])
else:
    print("3 saniye içinde oyuna geç...")
    time.sleep(3)
    with mss.mss() as sct:
        img = cv2.cvtColor(np.array(sct.grab(sct.monitors[1])), cv2.COLOR_BGRA2BGR)

kutular = cv2.selectROIs("Isim yazisini sec (ENTER = onayla, ESC = bitir)", img, showCrosshair=False)
cv2.destroyAllWindows()

for x, y, w, h in kutular:
    if w == 0 or h == 0:
        continue
    ad = input("Bu metnin adı (örn. ruh_metni): ").strip() or f"metin_{int(time.time())}"
    yol = os.path.join(KLASOR, f"{ad}.png")
    cv2.imwrite(yol, img[y:y + h, x:x + w])
    print("Kaydedildi:", yol)
