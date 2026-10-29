"""
Oyundan atılınca otomatik yeniden bağlanma.

Bot çalışırken birkaç saniyede bir kontrol edilir:
  - Oyun penceresi ("Farm2") önde değilse öne getirilir.
  - Sunucu seçimi ekranı  -> kanal seçili değilse KANAL seçilir, "Tamam"a tıklanır.
  - Giriş ekranı          -> kayıtlı hesap butonuna (HESAP_SABLON) tıklanır.
  - Karakter seçimi       -> Enter'a basılır.
Hiçbiri görünmüyorsa oyunda sayılır ve bot kaldığı yerden devam eder.

Şablonlar: templates/giris/ (server_sec, tamam, uolo2, karakter_sec)
"""
import ctypes
import ctypes.wintypes
import os
import time

import cv2
import mss
import numpy as np
import pydirectinput

# ---------------------------------------------------------------- AYARLAR
PENCERE_BASLIGI = "Farm2"          # Oyun penceresinin başlığı (tam eşleşme; "Farm2FullP..." klasörü karışmasın).
KONTROL_ARALIGI = 3.0              # Kaç saniyede bir bağlantı kontrol edilsin.
KANAL = 6                          # Hiçbir kanal seçili değilse seçilecek kanal (1-6).
SABLON_KLASOR = os.path.join("templates", "giris")
HESAP_SABLON = "uolo2"             # Giriş ekranında tıklanacak kayıtlı hesap butonu (templates/giris/uolo2.png).
ESIK = 0.85                        # Ekran şablonları eşleşme eşiği (yanlış ekranlarda en fazla ~0.76).
MAKS_SURE = 300                    # Yeniden bağlanma en fazla kaç saniye denensin.
# Kanal satırları "Server Seç" yazısının sol üst köşesine göre (piksel).
KANAL_OFSET = (153, 47)            # CH1 yazısının merkezi
KANAL_ARALIK = 21.2                # satırlar arası
# ------------------------------------------------------------------------

user32 = ctypes.windll.user32


def oyun_penceresi():
    """Başlığı tam olarak PENCERE_BASLIGI olan görünür pencereyi döndürür (yoksa 0)."""
    bulunan = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def geri_cagir(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.strip() == PENCERE_BASLIGI:
                bulunan.append(hwnd)
                return False
        return True

    user32.EnumWindows(geri_cagir, 0)
    return bulunan[0] if bulunan else 0


def pencere_bolgesi(hwnd):
    rect = ctypes.wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return {"left": pt.x, "top": pt.y, "width": rect.right, "height": rect.bottom}


def one_getir(hwnd):
    """Pencereyi simge durumundan çıkarıp öne getirir. Windows engellerse başlık çubuğuna tıklar."""
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows, arka plandaki bir programın pencere öne getirmesine izin vermez;
    # Alt'a basılınca izin veriyor.
    pydirectinput.press("alt")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    if user32.GetForegroundWindow() != hwnd:
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pydirectinput.click((rect.left + rect.right) // 2, rect.top + 10)
        time.sleep(0.5)
    return user32.GetForegroundWindow() == hwnd


def tikla(bolge, x, y):
    pydirectinput.moveTo(bolge["left"] + int(x), bolge["top"] + int(y))
    time.sleep(0.05)
    pydirectinput.click()


class Baglanti:
    def __init__(self):
        self.sablonlar = {}
        for ad in ("server_sec", "tamam", HESAP_SABLON, "karakter_sec"):
            t = cv2.imread(os.path.join(SABLON_KLASOR, ad + ".png"), cv2.IMREAD_GRAYSCALE)
            if t is None:
                print(f"UYARI: {SABLON_KLASOR}/{ad}.png yok, yeniden bağlanma kapalı.")
                self.sablonlar = {}
                break
            self.sablonlar[ad] = t
        self.sct = mss.mss()
        self.son_kontrol = 0.0
        self.pencere_uyarildi = False

    def bul(self, gri, ad):
        """Şablon eşiği geçerse sol üst köşesini (x, y) döndürür, yoksa None."""
        _, skor, _, konum = cv2.minMaxLoc(cv2.matchTemplate(gri, self.sablonlar[ad], cv2.TM_CCOEFF_NORMED))
        return konum if skor >= ESIK else None

    def merkez(self, konum, ad):
        th, tw = self.sablonlar[ad].shape[:2]
        return konum[0] + tw // 2, konum[1] + th // 2

    def ekran(self, hwnd):
        """(bölge, kare, durum) döndürür; durum: 'server', 'giris', 'karakter' ya da None (oyunda)."""
        bolge = pencere_bolgesi(hwnd)
        kare = cv2.cvtColor(np.array(self.sct.grab(bolge)), cv2.COLOR_BGRA2BGR)
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        for durum, ad in (("server", "server_sec"), ("giris", HESAP_SABLON), ("karakter", "karakter_sec")):
            if self.bul(gri, ad):
                return bolge, kare, durum
        return bolge, kare, None

    def kopuk_mu(self):
        """KONTROL_ARALIGI'nda bir: oyun penceresi önde değilse ya da giriş ekranlarından biri açıksa True."""
        if not self.sablonlar or time.time() - self.son_kontrol < KONTROL_ARALIGI:
            return False
        self.son_kontrol = time.time()
        hwnd = oyun_penceresi()
        if not hwnd:
            if not self.pencere_uyarildi:
                print(f"UYARI: '{PENCERE_BASLIGI}' penceresi bulunamadı (oyun kapalı mı?).")
                self.pencere_uyarildi = True
            return False
        self.pencere_uyarildi = False
        if user32.GetForegroundWindow() != hwnd:
            return True
        return self.ekran(hwnd)[2] is not None

    def kanal_secili(self, kare, server_konum):
        """Kanal satırlarından biri mavi vurguluysa True. Vurgulu satırda mavi, yeşilden ~35 fazla."""
        sx, sy = server_konum
        for n in range(6):
            cy = int(sy + KANAL_OFSET[1] + KANAL_ARALIK * n)
            x0 = sx + KANAL_OFSET[0] + 40   # yazının sağındaki boşluk: yalnızca zemin/vurgu
            parca = kare[cy - 6:cy + 6, x0:x0 + 55].astype(int)
            if parca.size and (parca[:, :, 0] - parca[:, :, 1]).mean() > 15:
                return True
        return False

    def baglan(self, devam_mi):
        """Oyuna girilene kadar ekranları sırayla geçer. devam_mi() False dönerse (duraklat/F10) bırakır."""
        print("!! Oyun penceresi önde değil ya da oyundan atıldı, yeniden bağlanılıyor...")
        bitis = time.time() + MAKS_SURE
        while time.time() < bitis and devam_mi():
            hwnd = oyun_penceresi()
            if not hwnd:
                print(f"   '{PENCERE_BASLIGI}' penceresi yok, bekleniyor...")
                time.sleep(5)
                continue
            if not one_getir(hwnd):
                print("   Pencere öne getirilemedi, tekrar denenecek...")
                time.sleep(2)
                continue
            bolge, kare, durum = self.ekran(hwnd)
            gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)

            if durum == "server":
                server = self.bul(gri, "server_sec")
                if not self.kanal_secili(kare, server):
                    print(f"   Kanal seçili değil, CH{KANAL} seçiliyor.")
                    tikla(bolge, server[0] + KANAL_OFSET[0], server[1] + KANAL_OFSET[1] + KANAL_ARALIK * (KANAL - 1))
                    time.sleep(0.5)
                    continue   # seçimin tuttuğunu bir sonraki turda kontrol et
                tamam = self.bul(gri, "tamam")
                if tamam:
                    print("   Sunucu seçimi: Tamam.")
                    tikla(bolge, *self.merkez(tamam, "tamam"))
                time.sleep(3)
            elif durum == "giris":
                print(f"   Giriş: {HESAP_SABLON} hesabına tıklanıyor.")
                tikla(bolge, *self.merkez(self.bul(gri, HESAP_SABLON), HESAP_SABLON))
                time.sleep(8)   # "Sunucuya bağlandı", "Giriş işlemi yapılıyor"
            elif durum == "karakter":
                print("   Karakter seçimi: Enter.")
                pydirectinput.press("enter")
                time.sleep(12)  # yükleme ekranı
            else:
                print("   Oyundayız, bot devam ediyor.")
                self.son_kontrol = time.time()
                return True
        print("   Yeniden bağlanılamadı.")
        return False
