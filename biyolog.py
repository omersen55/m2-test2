"""
Biyolog görevini düzenli aralıklarla teslim eder.

Sıra: minimap yanındaki yeşil biyolog ikonuna tıkla -> "Toplu Ver" -> başka bir pencere
(örn. seviye yetmiyor) açılırsa ESC -> biyolog penceresini X ile kapat.

Şablonlar: templates/biyolog/ (ikon, baslik, toplu_ver, tamam)
"""
import os
import time

import cv2
import pydirectinput

from yeniden_baglan import tikla

# ---------------------------------------------------------------- AYARLAR
ARALIK = 600                       # Kaç saniyede bir teslim edilsin (600 = 10 dk).
HATA_TEKRAR = 60                   # İkon/pencere bulunamazsa kaç saniye sonra tekrar denensin.
SABLON_KLASOR = os.path.join("templates", "biyolog")
TAMAM_BEKLE = 2.0                  # Toplu Ver'den sonra uyarı penceresi için en fazla kaç sn beklensin.
ESIK = 0.85
X_OFSET = (194, 10)                # "Biyolog Sistemi" başlığının sol üst köşesinden X butonunun merkezine.
# ------------------------------------------------------------------------


class Biyolog:
    def __init__(self):
        self.sablonlar = {}
        for ad in ("ikon", "baslik", "toplu_ver", "tamam"):
            t = cv2.imread(os.path.join(SABLON_KLASOR, ad + ".png"), cv2.IMREAD_GRAYSCALE)
            if t is None:
                print(f"UYARI: {SABLON_KLASOR}/{ad}.png yok, biyolog kapalı.")
                self.sablonlar = {}
                return
            self.sablonlar[ad] = t
        self.sonraki = time.time()   # bot başlar başlamaz bir kez teslim et

    def zamani_geldi(self):
        return bool(self.sablonlar) and time.time() >= self.sonraki

    def bul(self, kare, ad):
        """Şablon eşiği geçerse (sol üst köşe, merkez) döndürür, yoksa None."""
        t = self.sablonlar.get(ad)
        if t is None:
            return None
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        _, skor, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(gri, t, cv2.TM_CCOEFF_NORMED))
        if skor < ESIK:
            return None
        th, tw = t.shape[:2]
        return (x, y), (x + tw // 2, y + th // 2)

    def calistir(self, kare_al, bolge):
        """kare_al(bolge) -> BGR kare. Başarılıysa ARALIK, değilse HATA_TEKRAR sonra yeniden dener."""
        self.sonraki = time.time() + HATA_TEKRAR
        print(">> Biyolog teslim ediliyor...")

        ikon = self.bul(kare_al(bolge), "ikon")
        if not ikon:
            print(f"   Biyolog ikonu bulunamadı, {HATA_TEKRAR} sn sonra tekrar denenecek.")
            return
        tikla(bolge, *ikon[1])
        time.sleep(1.0)

        if not self.bul(kare_al(bolge), "baslik"):
            print(f"   Biyolog penceresi açılmadı, {HATA_TEKRAR} sn sonra tekrar denenecek.")
            return
        toplu = self.bul(kare_al(bolge), "toplu_ver")
        if toplu:
            tikla(bolge, *toplu[1])
        else:
            print("   Toplu Ver butonu bulunamadı.")

        # Seviye yetmiyorsa "Görev verebilmek için Seviyen .. olmalı" penceresi çıkıyor;
        # Tamam'a tıklamayla kapanmıyor, ESC ile kapanıyor. Çıkmazsa teslim zaten yapılmıştır.
        bitis = time.time() + TAMAM_BEKLE
        while time.time() < bitis:
            time.sleep(0.3)
            if self.bul(kare_al(bolge), "tamam"):
                print("   Uyarı penceresi (seviye yetmiyor): ESC.")
                pydirectinput.press("esc")
                time.sleep(0.5)
                break

        baslik = self.bul(kare_al(bolge), "baslik")
        if baslik:
            tikla(bolge, baslik[0][0] + X_OFSET[0], baslik[0][1] + X_OFSET[1])
            time.sleep(0.5)
        self.sonraki = time.time() + ARALIK
        print(f"   Biyolog tamam, sonraki {ARALIK // 60} dk sonra.")
