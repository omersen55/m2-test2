"""
Oyundan atılınca otomatik yeniden bağlanma.

Bot çalışırken birkaç saniyede bir kontrol edilir:
  - Oyun penceresi önde değilse öne getirilir.
  - Sunucu seçimi ekranı  -> kanal seçili değilse KANAL seçilir, "Tamam"a tıklanır.
  - Giriş ekranı          -> "Kayıtlı Hesap Bilgileri" altındaki hesap butonuna tıklanır.
                             Hesap adı verildiyse butonlar OCR ile okunup o hesap seçilir,
                             verilmediyse HESAP_SABLON resmine tıklanır.
  - Karakter seçimi       -> Enter'a basılır.
Hiçbiri görünmüyorsa oyunda sayılır ve bot kaldığı yerden devam eder.

Birden fazla oyun açıksa ayarla(karakter=...) ile hangi pencerenin kullanılacağı seçilir:
oyundayken başlığı "<KARAKTER> - Farm2" olan pencere bulunur ve hatırlanır. Oyundan atılınca
başlık "Farm2"ye dönse de aynı pencere kullanılmaya devam eder.

Şablonlar: templates/giris/ (server_sec, tamam, kayitli, karakter_sec, uolo2)
"""
import ctypes
import ctypes.wintypes
import difflib
import os
import time

import cv2
import mss
import numpy as np
import pydirectinput

try:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except ImportError:
    pytesseract = None

# ---------------------------------------------------------------- AYARLAR
PENCERE_BASLIGI = "Farm2"          # Oyun penceresinin başlığı: "Farm2" ya da "<karakter> - Farm2".
                                   # ("Farm2FullP..." klasör penceresi karışmasın diye tam eşleşme.)
KONTROL_ARALIGI = 3.0              # Kaç saniyede bir bağlantı kontrol edilsin.
KANAL = 6                          # Hiçbir kanal seçili değilse seçilecek kanal (1-6).
SABLON_KLASOR = os.path.join("templates", "giris")
HESAP_SABLON = "uolo2"             # Hesap adı verilmezse tıklanacak buton (templates/giris/uolo2.png).
ESIK = 0.85                        # Ekran şablonları eşleşme eşiği (yanlış ekranlarda en fazla ~0.76).
MAKS_SURE = 300                    # Yeniden bağlanma en fazla kaç saniye denensin.
# Kanal satırları "Server Seç" yazısının sol üst köşesine göre (piksel).
KANAL_OFSET = (153, 47)            # CH1 yazısının merkezi
KANAL_ARALIK = 21.2                # satırlar arası
# Kayıtlı hesap butonları "Kayıtlı Hesap Bilgileri" yazısının sol üst köşesine göre (piksel).
HESAP_SUTUN_X = (-50, 66)          # iki sütunun sol kenarı
HESAP_SATIR_Y = 25                 # ilk satırın üst kenarı
HESAP_SATIR_ARALIK = 31
HESAP_SATIR = 3
HESAP_BUTON = (105, 21)            # buton genişlik, yükseklik
# ------------------------------------------------------------------------

user32 = ctypes.windll.user32

KARAKTER = ""                      # ayarla() ile verilir; boşsa ilk bulunan oyun penceresi kullanılır.
_pencere = 0                       # karakterin penceresi bulununca burada tutulur


def ayarla(karakter=""):
    """Hangi karakterin penceresiyle çalışılacağını seçer ("" = ilk bulunan oyun penceresi)."""
    global KARAKTER, _pencere
    KARAKTER = karakter.strip()
    _pencere = 0


def _baslik(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value.strip()


def _oyun_basligi_mi(baslik):
    # Giriş ekranlarında "Farm2", oyundayken "REDIS - Farm2" (karakter adı - Farm2).
    return baslik == PENCERE_BASLIGI or baslik.endswith(" - " + PENCERE_BASLIGI)


def oyun_pencereleri():
    """Görünür bütün oyun pencerelerini [(hwnd, başlık), ...] olarak döndürür."""
    bulunan = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def geri_cagir(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            baslik = _baslik(hwnd)
            if _oyun_basligi_mi(baslik):
                bulunan.append((hwnd, baslik))
        return True

    user32.EnumWindows(geri_cagir, 0)
    return bulunan


def oyun_penceresi():
    """Kullanılacak oyun penceresini döndürür (yoksa 0).

    KARAKTER verildiyse önce daha önce bulunan pencere (hâlâ açıksa), sonra başlığı
    "<KARAKTER> - Farm2" olan pencere aranır. Hiçbiri yoksa ve tek oyun giriş ekranında açıksa o kullanılır.
    """
    global _pencere
    hedef = f"{KARAKTER} - {PENCERE_BASLIGI}".lower()
    if _pencere and user32.IsWindow(_pencere):
        baslik = _baslik(_pencere)
        # Oyundan atılınca başlık "Farm2"ye döner; o pencere yine bizim karakterin penceresi.
        if baslik == PENCERE_BASLIGI or baslik.lower() == hedef:
            return _pencere
    pencereler = oyun_pencereleri()
    if not KARAKTER:
        return pencereler[0][0] if pencereler else 0
    for hwnd, baslik in pencereler:
        if baslik.lower() == hedef:
            _pencere = hwnd
            return hwnd
    # Tek oyun açık ve giriş ekranındaysa (başlıkta karakter adı yok) o pencere kullanılır.
    # Başka bir karakterle oyundaysa kullanılmaz; yanlış karaktere tıklanmasın.
    if len(pencereler) == 1 and pencereler[0][1] == PENCERE_BASLIGI:
        return pencereler[0][0]
    return 0


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


def _sade(metin):
    """OCR'ın karıştırdığı harfleri eşitler: l/1/i/ı/| -> 1, o -> 0 (uolo1 -> u0101)."""
    tablo = str.maketrans({"l": "1", "i": "1", "ı": "1", "|": "1", "!": "1", "o": "0",
                           "ş": "s", "ğ": "g", "ü": "u", "ö": "0", "ç": "c"})
    return "".join(ch for ch in metin.lower().translate(tablo) if ch.isalnum())


class Baglanti:
    def __init__(self, hesap=""):
        self.hesap = hesap.strip()
        self.sablonlar = {}
        adlar = ["server_sec", "tamam", "kayitli", "karakter_sec"]
        if not self.hesap:
            adlar.append(HESAP_SABLON)
        for ad in adlar:
            t = cv2.imread(os.path.join(SABLON_KLASOR, ad + ".png"), cv2.IMREAD_GRAYSCALE)
            if t is None:
                print(f"UYARI: {SABLON_KLASOR}/{ad}.png yok, yeniden bağlanma kapalı.")
                self.sablonlar = {}
                break
            self.sablonlar[ad] = t
        if self.hesap and pytesseract is None:
            print("UYARI: pytesseract yok, hesap adı okunamaz; yeniden bağlanmada hesap seçilemeyecek.")
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
        """(bölge, kare, durum) döndürür; durum: 'server', 'giris', 'karakter', 'kucuk'
        (pencere simge durumunda, kare None) ya da None (oyunda)."""
        bolge = pencere_bolgesi(hwnd)
        if bolge["width"] <= 0 or bolge["height"] <= 0:   # simge durumunda: görüntü yok
            return bolge, None, "kucuk"
        kare = cv2.cvtColor(np.array(self.sct.grab(bolge)), cv2.COLOR_BGRA2BGR)
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        for durum, ad in (("server", "server_sec"), ("giris", "kayitli"), ("karakter", "karakter_sec")):
            if self.bul(gri, ad):
                return bolge, kare, durum
        return bolge, kare, None

    def hesap_butonlari(self, gri):
        """Kayıtlı hesap butonlarını [(okunan yazı, merkez), ...] olarak döndürür."""
        baslik = self.bul(gri, "kayitli")
        if not baslik or pytesseract is None:
            return []
        bw, bh = HESAP_BUTON
        butonlar = []
        for satir in range(HESAP_SATIR):
            for sx in HESAP_SUTUN_X:
                x = baslik[0] + sx
                y = baslik[1] + HESAP_SATIR_Y + HESAP_SATIR_ARALIK * satir
                parca = gri[y + 3:y + bh - 2, x + 8:x + bw - 8]
                if parca.size == 0:
                    continue
                buyuk = 255 - cv2.resize(parca, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                yazi = pytesseract.image_to_string(buyuk, config="--psm 7").strip()
                butonlar.append((yazi, (x + bw // 2, y + bh // 2)))
        return butonlar

    def hesap_konumu(self, gri):
        """Tıklanacak hesap butonunun merkezini döndürür (bulunamazsa None)."""
        if not self.hesap:
            konum = self.bul(gri, HESAP_SABLON)
            return self.merkez(konum, HESAP_SABLON) if konum else None
        butonlar = self.hesap_butonlari(gri)
        aranan = _sade(self.hesap)
        for yazi, merkez in butonlar:
            if _sade(yazi) == aranan:
                return merkez
        # Tam tutmadıysa en benzeyen; ama yalnızca açık ara öndeyse (uolo1/uolo2 karışmasın).
        puanlar = sorted(((difflib.SequenceMatcher(None, _sade(y), aranan).ratio(), m, y)
                          for y, m in butonlar), key=lambda p: -p[0])
        if puanlar and puanlar[0][0] >= 0.85 and (len(puanlar) == 1 or puanlar[1][0] < puanlar[0][0]):
            return puanlar[0][1]
        okunan = ", ".join(y for y, _ in butonlar) or "hiçbiri"
        print(f"   '{self.hesap}' hesabı bulunamadı. Okunan butonlar: {okunan}")
        return None

    def kopuk_mu(self):
        """KONTROL_ARALIGI'nda bir: oyun penceresi önde değilse ya da giriş ekranlarından biri açıksa True."""
        if not self.sablonlar or time.time() - self.son_kontrol < KONTROL_ARALIGI:
            return False
        self.son_kontrol = time.time()
        hwnd = oyun_penceresi()
        if not hwnd:
            if not self.pencere_uyarildi:
                ad = f"'{KARAKTER} - {PENCERE_BASLIGI}'" if KARAKTER else f"'{PENCERE_BASLIGI}'"
                print(f"UYARI: {ad} penceresi bulunamadı (oyun kapalı mı, karakter adı doğru mu?).")
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
                print("   Oyun penceresi yok, bekleniyor...")
                time.sleep(5)
                continue
            if not one_getir(hwnd):
                print("   Pencere öne getirilemedi, tekrar denenecek...")
                time.sleep(2)
                continue
            bolge, kare, durum = self.ekran(hwnd)
            if durum == "kucuk":
                print("   Oyun penceresi simge durumunda, açılması bekleniyor...")
                time.sleep(1)
                continue
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
                konum = self.hesap_konumu(gri)
                if konum:
                    print(f"   Giriş: {self.hesap or HESAP_SABLON} hesabına tıklanıyor.")
                    tikla(bolge, *konum)
                    time.sleep(8)   # "Sunucuya bağlandı", "Giriş işlemi yapılıyor"
                else:
                    time.sleep(5)
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
