"""
Tecrübe yüzüğü ve hırsız eldivenini sürekli takılı tutar.

Envanter penceresi açık durmalı; yüzük ve eldiven envanterin açık sayfasında görünmeli.
KONTROL_ARALIGI'nda bir ekipman paneline bakılır. Yüzük ya da eldiven takılı değilse
(süresi dolup kaybolduysa) envanterdeki aynısına sağ tıklanır. Süre saymaya gerek kalmaz,
takılı olan da yanlışlıkla değiştirilmez.

Şablonlar: templates/ekipman/ (envanter = pencere başlığındaki yazı, yuzuk, eldiven)
"""
import os
import time

import cv2
import numpy as np
import pydirectinput

# ---------------------------------------------------------------- AYARLAR
KONTROL_ARALIGI = 60               # Kaç saniyede bir kontrol edilsin.
SABLON_KLASOR = os.path.join("templates", "ekipman")
ESYALAR = {"yuzuk": "Tecrübe yüzüğü", "eldiven": "Hırsız eldiveni"}
ESIK = 0.85                        # Envanterdeki eşya ~1.00, takılı olan ~0.95, başka yerler en fazla ~0.79.
# Konumlar "Envanter" yazısının sol üst köşesine göre (piksel):
EKIPMAN_SINIR = 270                # Bundan yukarısı takılı eşyalar (~225), aşağısı envanter (~307).
PENCERE_YATAY = (-110, 130)        # Envanter penceresinin yatay sınırları (yalnızca bu aralıkta aranır).
# ------------------------------------------------------------------------


def sag_tikla(bolge, x, y):
    pydirectinput.moveTo(bolge["left"] + int(x), bolge["top"] + int(y))
    time.sleep(0.05)
    pydirectinput.click(button="right")


class Ekipman:
    def __init__(self, esyalar=tuple(ESYALAR)):
        """esyalar: takılı tutulacaklar, ör. ["yuzuk"]. Boşsa bu özellik kapalı."""
        self.sablonlar = {}
        self.esyalar = [ad for ad in ESYALAR if ad in esyalar]
        self.sonraki = time.time()
        self.uyarilanlar = set()
        if not self.esyalar:
            return
        for ad in ("envanter", *self.esyalar):
            t = cv2.imread(os.path.join(SABLON_KLASOR, ad + ".png"), cv2.IMREAD_GRAYSCALE)
            if t is None:
                print(f"UYARI: {SABLON_KLASOR}/{ad}.png yok, yüzük/eldiven takma kapalı.")
                self.sablonlar = {}
                return
            self.sablonlar[ad] = t

    def zamani_geldi(self):
        return bool(self.sablonlar) and time.time() >= self.sonraki

    def uyar(self, anahtar, mesaj):
        if anahtar not in self.uyarilanlar:
            print(mesaj)
            self.uyarilanlar.add(anahtar)

    def tara(self, gri):
        """{ad: (takili_mi, envanterdeki merkez ya da None)} döndürür; envanter kapalıysa None."""
        _, skor, _, (bx, by) = cv2.minMaxLoc(
            cv2.matchTemplate(gri, self.sablonlar["envanter"], cv2.TM_CCOEFF_NORMED))
        if skor < ESIK:
            return None
        x0 = max(0, bx + PENCERE_YATAY[0])
        x1 = min(gri.shape[1], bx + PENCERE_YATAY[1])
        alan = gri[by:, x0:x1]
        durum = {}
        for ad in self.esyalar:
            t = self.sablonlar[ad]
            th, tw = t.shape[:2]
            if alan.shape[0] < th or alan.shape[1] < tw:
                return None
            sonuc = cv2.matchTemplate(alan, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(sonuc >= ESIK)
            takili = any(y + th // 2 < EKIPMAN_SINIR for y in ys)
            envanter = [(sonuc[y, x], x, y) for x, y in zip(xs, ys) if y + th // 2 >= EKIPMAN_SINIR]
            konum = None
            if envanter:
                _, x, y = max(envanter)
                konum = (x0 + x + tw // 2, by + y + th // 2)
            durum[ad] = (takili, konum)
        return durum

    def calistir(self, kare_al, bolge, once=None):
        """kare_al(bolge) -> BGR kare. Sağ tıklamadan hemen önce once() çağrılır (ör. boşluğu bırak)."""
        self.sonraki = time.time() + KONTROL_ARALIGI
        durum = self.tara(cv2.cvtColor(kare_al(bolge), cv2.COLOR_BGR2GRAY))
        if durum is None:
            self.uyar("pencere", "   Envanter penceresi açık değil, yüzük/eldiven kontrol edilemiyor.")
            return
        self.uyarilanlar.discard("pencere")
        tiklandi = False
        for ad, (takili, konum) in durum.items():
            if takili:
                self.uyarilanlar.discard(ad)
                continue
            if konum is None:
                self.uyar(ad, f"   {ESYALAR[ad]} takılı değil ve envanterde yok "
                              "(bitti mi, envanterde doğru sayfa açık mı?).")
                continue
            if once and not tiklandi:
                once()
            print(f">> {ESYALAR[ad]} takılı değil, envanterden takılıyor.")
            sag_tikla(bolge, *konum)
            tiklandi = True
            time.sleep(0.5)
        if tiklandi:
            # Fare eşyanın üstünde kalırsa açıklama kutusu ekipman panelini kapatabilir.
            pydirectinput.moveTo(bolge["left"] + bolge["width"] // 2, bolge["top"] + bolge["height"] // 2)
