"""
Oyun ekranındaki soru kutusunu ve seçenek butonlarını yazıya döker.

Kullanım:
    python oku.py ornek.png      -> resim dosyasından okur
    python oku.py                -> o anki ekran görüntüsünden okur
"""
import sys

import cv2
import mss
import numpy as np
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Yazılar açık gri / beyaz: düşük doygunluk, yüksek parlaklık.
SAT_MAX = 60
VAL_MIN = 120
MIN_SECENEK_GENIS = 14  # px — bundan dar bloklar seçenek sayılmaz


def ekran_goruntusu():
    with mss.mss() as sct:
        shot = np.array(sct.grab(sct.monitors[1]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def yazi_maskesi(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 1] < SAT_MAX) & (hsv[:, :, 2] > VAL_MIN)).astype(np.uint8) * 255


def yazi_bloklari(mask):
    """Harfleri yatayda birleştirip her kelime grubunun kutusunu döndürür."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
    n, _, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, k))
    return [tuple(st[i][:4]) for i in range(1, n) if st[i][4] > 30 and 6 < st[i][3] < 30]


def secenek_satiri(bloklar):
    """Aynı yükseklikte yan yana duran en kalabalık blok grubunu (butonları) bulur."""
    en_iyi = []
    for _, y, _, h in bloklar:
        orta = y + h / 2
        grup = [b for b in bloklar if abs((b[1] + b[3] / 2) - orta) < 6]
        if len(grup) > len(en_iyi):
            en_iyi = grup
    return sorted(en_iyi, key=lambda b: b[0])


def oku(img, kutu):
    x, y, w, h = kutu
    p = 4
    crop = img[max(0, y - p):y + h + p, max(0, x - p):x + w + p]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Küçük oyun fontu için: 6x büyüt, hafif yumuşat, siyah yazı / beyaz zemin yap
    g = cv2.resize(g, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    g = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    g = cv2.copyMakeBorder(g, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    txt = pytesseract.image_to_string(g, lang="tur+eng", config="--psm 7").strip()
    txt = txt.replace("â", "4")  # oyun 'a' yerine '4' kullanıyor, OCR bunu 'â' sanabiliyor
    return txt.strip(" |)!")


def coz(img):
    soru, metinler, _ = coz_kutulu(img)
    return soru, metinler


def coz_kutulu(img):
    """coz ile aynı, ek olarak seçenek kutularını (x, y, w, h) de döndürür."""
    bloklar = yazi_bloklari(yazi_maskesi(img))
    # Arkadaki isim yazısı/taş parçaları da aynı satıra düşebiliyor (9-11 px genişlik);
    # en kısa gerçek şık ("8-3") ~24 px.
    secenekler = [b for b in secenek_satiri(bloklar) if b[2] >= MIN_SECENEK_GENIS]
    if len(secenekler) < 2:
        return None, [], []

    sol = secenekler[0][0] - 20
    sag = secenekler[-1][0] + secenekler[-1][2] + 20
    ust = min(b[1] for b in secenekler)

    # Soru: seçeneklerin üstünde, aynı yatay aralıkta kalan en geniş blok
    adaylar = [b for b in bloklar if b[1] + b[3] < ust and b[0] >= sol and b[0] + b[2] <= sag]
    soru_kutu = max(adaylar, key=lambda b: b[2]) if adaylar else None

    soru = oku(img, soru_kutu) if soru_kutu else ""
    return soru, [oku(img, b) for b in secenekler], secenekler


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        img = cv2.imread(sys.argv[1])
        if img is None:
            sys.exit(f"Resim açılamadı: {sys.argv[1]}")
    else:
        img = ekran_goruntusu()

    soru, secenekler = coz(img)
    if soru is None:
        sys.exit("Seçenek kutuları bulunamadı.")

    print("Soru:", soru)
    for i, s in enumerate(secenekler, 1):
        print(f"{i}) {s}")


if __name__ == "__main__":
    main()
