"""
Örümcek zindanı botu.

Karakteri odanın ortasındaki taşın üstüne getir, "-" tuşu ile başlat.
- Boşluk basılı tutulur (etraftaki örümceklere vurur), pelerin tuşuna düzenli basılır (mobları toplar).
- Ölünce "Burada yeniden başla"ya tıklar, moblardan uzak bir noktaya yürür, can dolana kadar
  bekler, aynı yoldan geri yürüyerek odanın ortasına döner ve devam eder.
- Doğrulama penceresi gelirse bot_ocr.py ile aynı şekilde LLM'e sorup cevaplar.

Şablon: templates/zindan/yeniden_basla.png  ("Burada yeniden başla" butonunun yazısı)
"""
import os
import time

import cv2
import pydirectinput

from bot_ocr import BASLAT_TUSU, UYARI_ESIK, Bot, oyun_bolgesi, tikla

# ---------------------------------------------------------------- AYARLAR
SALDIRI_TUSU = "space"             # Basılı tutulan saldırı tuşu.
PELERIN_TUSU = "4"                 # Pelerin (mob toplama) tuşu.
PELERIN_ARALIK = 0.5               # Pelerine kaç saniyede bir basılsın (0.5 = saniyede 2 kez).
YENIDEN_BASLA_SABLON = os.path.join("templates", "zindan", "yeniden_basla.png")
OLUM_ESIK = 0.85                   # "Burada yeniden başla" butonu eşleşme eşiği. Altındaki "Şehirde
                                   # yeniden başla" ~0.73 alıyor; eşiği bunun altına indirme.
BINEK_TUSLARI = ("ctrl", "g")      # Yeniden başlayınca ata binme kısayolu (None = kapalı).
KACIS_OFSET = (0, 250)             # Ölünce yürünecek nokta: ekran merkezine göre (x, y) piksel.
                                   # Moblardan uzak, boş bir yer olmalı.
MERKEZ_SABLON = os.path.join("templates", "zindan", "merkez.png")   # Ortadaki platformun alt kenarı.
MERKEZ_OFSET = (155, -70)          # Şablonun sol üst köşesinden platform ortasına (piksel).
MERKEZ_ESIK = 0.70                 # Platform bulunamazsa kaçışın tersi yönüne tıklanarak dönülür.
MERKEZ_TOLERANS = 40               # Platform ortası ekran merkezine bu kadar yakınsa "vardık" sayılır.
YURUME_SURESI = 3.0                # Tıklanan noktaya yürüme süresi (sn).
CAN_DOLMA_SURESI = 8.0             # Kaçış noktasında can dolsun diye beklenecek süre (sn).
KONTROL_ARALIK = 0.1               # Saldırı sırasında ekran kontrol aralığı (sn).
# ------------------------------------------------------------------------


class Zindan(Bot):
    def __init__(self):
        super().__init__()
        self.olum_sablon = cv2.imread(YENIDEN_BASLA_SABLON, cv2.IMREAD_GRAYSCALE)
        if self.olum_sablon is None:
            print(f"UYARI: {YENIDEN_BASLA_SABLON} yok, ölüm algılanamayacak.")
        self.merkez_sablon = cv2.imread(MERKEZ_SABLON, cv2.IMREAD_GRAYSCALE)
        if self.merkez_sablon is None:
            print(f"UYARI: {MERKEZ_SABLON} yok, merkeze yalnızca ters yönde yürünerek dönülecek.")
        self.basili = False
        self.son_zayif_log = 0.0

    def uyari_var(self, kare):
        """Bot.uyari_var ile aynı; ek olarak eşiğe yaklaşıp geçemeyen eşleşmeleri raporlar
        (zindanın koyu zemininde başlık şablonu daha düşük skor alabiliyor)."""
        if not self.uyarilar:
            return False
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        skor = max(cv2.matchTemplate(gri, t, cv2.TM_CCOEFF_NORMED).max() for t in self.uyarilar)
        if 0.5 <= skor < UYARI_ESIK and time.time() - self.son_zayif_log > 2:
            print(f"   (doğrulama şablonu zayıf eşleşti: {skor:.2f}, eşik {UYARI_ESIK}) -> debug_uyari.png")
            cv2.imwrite("debug_uyari.png", kare)
            self.son_zayif_log = time.time()
        return skor >= UYARI_ESIK

    def bosluk(self, bas):
        """Saldırı tuşunu basılı tut / bırak (aynı durumdaysa bir şey yapmaz)."""
        if bas != self.basili:
            (pydirectinput.keyDown if bas else pydirectinput.keyUp)(SALDIRI_TUSU)
            self.basili = bas

    def yeniden_basla_butonu(self, kare):
        """Ölüm penceresi açıksa butonun merkezini (x, y) döndürür, yoksa None."""
        if self.olum_sablon is None:
            return None
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        sonuc = cv2.matchTemplate(gri, self.olum_sablon, cv2.TM_CCOEFF_NORMED)
        _, skor, _, (x, y) = cv2.minMaxLoc(sonuc)
        if skor < OLUM_ESIK:
            return None
        th, tw = self.olum_sablon.shape[:2]
        return x + tw // 2, y + th // 2

    def platform_merkezi(self, kare):
        """Ortadaki platformu bulursa ortasının (x, y) konumunu döndürür, yoksa None."""
        if self.merkez_sablon is None:
            return None
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        sonuc = cv2.matchTemplate(gri, self.merkez_sablon, cv2.TM_CCOEFF_NORMED)
        _, skor, _, (x, y) = cv2.minMaxLoc(sonuc)
        if skor < MERKEZ_ESIK:
            return None
        return x + MERKEZ_OFSET[0], y + MERKEZ_OFSET[1]

    def merkeze_don(self, bolge):
        """Platform görünüyorsa ortasına tıklar, vardıktan sonra bir kez daha kontrol edip düzeltir.
        Platform görünmüyorsa kaçış yolunun tersine yürür."""
        cx, cy = bolge["width"] // 2, bolge["height"] // 2
        for deneme in range(2):
            hedef = self.platform_merkezi(self.kare_al(bolge))
            if hedef is None:
                if deneme == 0:
                    print("   Platform bulunamadı, geldiği yoldan dönülüyor...")
                    tikla(bolge, cx - KACIS_OFSET[0], cy - KACIS_OFSET[1])
                    self.bekle_cevapla(YURUME_SURESI, bolge)
                return
            if abs(hedef[0] - cx) <= MERKEZ_TOLERANS and abs(hedef[1] - cy) <= MERKEZ_TOLERANS:
                return
            print("   Platformun ortasına yürünüyor..." if deneme == 0 else "   Konum düzeltiliyor...")
            tikla(bolge, *hedef)
            if not self.bekle_cevapla(YURUME_SURESI, bolge):
                return

    def bekle_cevapla(self, sure, bolge):
        """Süre boyunca bekler; doğrulama gelirse cevaplayıp beklemeye devam eder.
        Duraklatılırsa ya da F10'a basılırsa False döner."""
        bitis = time.time() + sure
        while time.time() < bitis:
            if not self.calisiyor or self.cikis:
                return False
            if self.uyari_var(self.kare_al(bolge)):
                self.uyari_bekle(bolge)
            time.sleep(0.3)
        return True

    def dirilt(self, bolge, buton):
        """Yeniden başla -> ata bin -> kaçış noktasına yürü -> can dolsun -> merkeze geri dön."""
        self.bosluk(False)
        print("!! Öldün. Burada yeniden başlanıyor...")
        tikla(bolge, *buton)
        time.sleep(1.5)

        if BINEK_TUSLARI:
            print("   Ata biniliyor...")
            pydirectinput.keyDown(BINEK_TUSLARI[0])
            pydirectinput.press(BINEK_TUSLARI[1])
            pydirectinput.keyUp(BINEK_TUSLARI[0])
            time.sleep(1.0)

        # Kamera karakteri ekranın ortasında tutar; kaçış noktası merkeze göre verilir.
        cx, cy = bolge["width"] // 2, bolge["height"] // 2
        tikla(bolge, cx + KACIS_OFSET[0], cy + KACIS_OFSET[1])
        print(f"   Kaçış noktasına yürünüyor, {CAN_DOLMA_SURESI:.0f} sn can doldurulacak...")
        if not self.bekle_cevapla(YURUME_SURESI + CAN_DOLMA_SURESI, bolge):
            return
        print("   Odanın ortasına dönülüyor...")
        self.merkeze_don(bolge)

    def calistir(self):
        print(f"Karakteri odanın ortasına getir. '{BASLAT_TUSU}' = başlat/duraklat, F10 = çıkış")
        son_pelerin = 0.0
        while not self.cikis:
            if not self.calisiyor:
                self.bosluk(False)
                time.sleep(0.1)
                continue
            if self.baglanti.kopuk_mu():
                self.bosluk(False)
                self.baglanti.baglan(lambda: self.calisiyor and not self.cikis)
                continue
            if self.biyolog.zamani_geldi():
                self.bosluk(False)
                self.biyolog.calistir(self.kare_al, oyun_bolgesi())
                continue
            bolge = oyun_bolgesi()
            kare = self.kare_al(bolge)
            if self.uyari_var(kare):
                self.bosluk(False)
                self.uyari_bekle(bolge)
                continue
            buton = self.yeniden_basla_butonu(kare)
            if buton:
                self.dirilt(bolge, buton)
                continue

            self.bosluk(True)
            simdi = time.time()
            if simdi - son_pelerin >= PELERIN_ARALIK:
                pydirectinput.press(PELERIN_TUSU)
                son_pelerin = simdi
            time.sleep(KONTROL_ARALIK)
        self.bosluk(False)
        print("Çıkılıyor.")


if __name__ == "__main__":
    Zindan().calistir()
