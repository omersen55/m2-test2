import ctypes
import ctypes.wintypes
import glob
import os
import random
import time

import cv2
import keyboard
import mss
import numpy as np
import pydirectinput

import oku
import yeniden_baglan
try:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

    print("Tesseract:", pytesseract.get_tesseract_version())
    print("Diller:", pytesseract.get_languages(config=""))

except ImportError:
    pytesseract = None
    print("pytesseract kurulu değil.")

# ---------------------------------------------------------------- AYARLAR
OYUN_PENCERE_BASLIGI = ""         # Boş = o an önde olan pencere. Yazılırsa başlığında bu geçen pencere
                                   # kullanılır (örn. "ANTHOS"). Bulunamazsa tüm ekran kullanılır.
ESIK = 0.70                        # İsim yazısı eşleşme eşiği (0-1). Yanlış tespit varsa artır, kaçırıyorsa azalt.
ISIM_GOVDE_FARKI = 68              # İsim yazısı ile metin gövdesi arasındaki dikey mesafe (piksel).
TAKIP_MODU = True                  # True: tıklanan metnin isim yazısı takip edilir, yazı kaybolunca
                                   #       metin kırıldı sayılıp hemen sıradakine geçilir.
                                   # False: aşağıdaki SALDIRI_SURESI kadar körlemesine beklenir.
SALDIRI_SURESI = (6, 6)            # (TAKIP_MODU=False iken) tıklamadan sonra beklenecek süre (sn).
KAYIP_SURESI = 0.8                 # Yazı bu kadar saniye görünmezse metin kırıldı sayılır.
MAKS_SURE = {                      # Bir metine en fazla kaç sn vurulsun (takılırsa sonrakine geçer).
    "golge_metni": 120,
    "varsayilan": 60,
}
YENIDEN_TIKLA_SURESI = 5.0         # Bu süre geçtiği halde karakter metne ulaşmadıysa tekrar tıkla.
ULASTI_YARICAP = 180               # Metin karaktere bu kadar yakınsa (piksel) "vuruyor" sayılır.
ULASAMAZSA_TIKLAMA = 3             # Bu kadar tekrar tıklamaya rağmen ulaşılamazsa metin "takılı" sayılır.
ATLA_SURESI = 180                  # Takılı metin bu kadar saniye boyunca atlanır.
ATLA_YARICAP = 60                  # Atlanan metnin konumuna bu kadar yakın olan metinler seçilmez.
TOPLAMA_TUSU = None                # Metin bitince yerdeki eşyaları toplama tuşu (None = kapalı).
TOPLAMA_SAYISI = 2                 # Toplama tuşuna kaç kez basılsın.
KAMERA_DONDUR_TUSU = "e"           # Metin bulunamazsa kamerayı döndürme tuşu (None = kapalı).
ARAYUZ_KENAR_BOSLUGU = 0.08        # Ekranın alt/üst %8'ini yoksay (sohbet kutusu, barlar).
BASLAT_TUSU = "-"                  # Başlat/duraklat tuşu.
HATA_AYIKLAMA = False              # True ise tespitleri bir pencerede gösterir.
UYARI_ESIK = 0.70                  # Doğrulama penceresi tespit eşiği. Gerçek pencere 0.76+,
                                   # pencere olmayan ekranlar en fazla ~0.52 alıyor.
# ------------------------------------------------------------------------

pydirectinput.PAUSE = 0.02
pydirectinput.FAILSAFE = False

try:  # Windows ölçeklendirmesinde (%125, %150) koordinatlar kaymasın
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()


def sablonlari_yukle(klasor="templates/isim"):
    """templates/isim/*.png -> [(ad, gri_sablon), ...]"""
    sablonlar = []
    for yol in sorted(glob.glob(os.path.join(klasor, "*.png"))):
        img = cv2.imread(yol, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            sablonlar.append((os.path.splitext(os.path.basename(yol))[0], img))
    if not sablonlar:
        raise SystemExit("templates/isim/ klasöründe şablon yok. Önce: python sablon_al.py")
    return sablonlar


def pencere_bul(parca):
    """Başlığında `parca` geçen ilk görünür pencereyi döndürür."""
    user32 = ctypes.windll.user32
    bulunan = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def geri_cagir(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if parca.lower() in buf.value.lower():
                bulunan.append(hwnd)
                return False
        return True

    user32.EnumWindows(geri_cagir, 0)
    return bulunan[0] if bulunan else 0


def oyun_bolgesi():
    """Oyun penceresinin istemci alanını (ekran koordinatlarında) döndürür."""
    user32 = ctypes.windll.user32
    if yeniden_baglan.KARAKTER:   # arayüzden karakter adı verildiyse o karakterin penceresi
        hwnd = yeniden_baglan.oyun_penceresi()
    elif OYUN_PENCERE_BASLIGI:
        hwnd = pencere_bul(OYUN_PENCERE_BASLIGI)
    else:
        hwnd = user32.GetForegroundWindow()
    if hwnd:
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        if rect.right > 0 and rect.bottom > 0:
            return {"left": pt.x, "top": pt.y, "width": rect.right, "height": rect.bottom}
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return {"left": 0, "top": 0, "width": w, "height": h}


def metinleri_bul(kare, sablonlar, esik=ESIK):
    """Karedeki metinleri [(x, y, skor, ad), ...] olarak döndürür (x, y = gövde merkezi)."""
    gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
    adaylar = []
    for ad, t in sablonlar:
        th, tw = t.shape[:2]
        sonuc = cv2.matchTemplate(gri, t, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(sonuc >= esik)
        for x, y in zip(xs, ys):
            # Tıklanacak nokta: yazının altındaki metin gövdesi
            adaylar.append((int(x + tw / 2), int(y + th / 2 + ISIM_GOVDE_FARKI),
                            float(sonuc[y, x]), ad))

    # Aynı yazıya ait yan yana eşleşmeleri birleştir (en yüksek skor kalır)
    adaylar.sort(key=lambda a: -a[2])
    secilen = []
    for a in adaylar:
        if all(abs(a[0] - s[0]) > 40 or abs(a[1] - s[1]) > 10 for s in secilen):
            secilen.append(a)

    h = kare.shape[0]
    ust, alt = h * ARAYUZ_KENAR_BOSLUGU, h * (1 - ARAYUZ_KENAR_BOSLUGU)
    return [m for m in secilen if ust < m[1] < alt]


def isim_ara(gri, sablon, nokta, yaricap):
    """`nokta` (yazı merkezi) çevresinde `yaricap` içinde bu yazıyı arar.
    Birden fazla varsa noktaya en yakın olanı (x, y) döndürür, yoksa None."""
    th, tw = sablon.shape[:2]
    H, W = gri.shape[:2]
    x0 = max(0, int(nokta[0] - yaricap - tw / 2))
    y0 = max(0, int(nokta[1] - yaricap - th / 2))
    x1 = min(W, int(nokta[0] + yaricap + tw / 2))
    y1 = min(H, int(nokta[1] + yaricap + th / 2))
    if x1 - x0 < tw or y1 - y0 < th:
        return None
    sonuc = cv2.matchTemplate(gri[y0:y1, x0:x1], sablon, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(sonuc >= ESIK)
    if len(xs) == 0:
        return None
    cx = xs + x0 + tw / 2
    cy = ys + y0 + th / 2
    d = (cx - nokta[0]) ** 2 + (cy - nokta[1]) ** 2
    i = int(np.argmin(d))
    if d[i] > yaricap ** 2:
        return None
    return float(cx[i]), float(cy[i])


def en_yakin(metinler, merkez):
    cx, cy = merkez
    return min(metinler, key=lambda m: (m[0] - cx) ** 2 + (m[1] - cy) ** 2)


def tikla(bolge, x, y):
    pydirectinput.moveTo(bolge["left"] + x, bolge["top"] + y)
    time.sleep(0.05)
    pydirectinput.click()


class Bot:
    def __init__(self, ayar=None, kisayol=True):
        """ayar: {"karakter", "hesap", "biyolog", "yuzuk", "eldiven"} (arayüzden gelir).
        kisayol: True ise '-' ve F10 tuşları burada tanımlanır (arayüz kendisi tanımlar)."""
        ayar = ayar or {}
        self.calisiyor = False
        self.cikis = False
        self.sablonlar = sablonlari_yukle()
        self.uyarilar = [img for img in (cv2.imread(y, cv2.IMREAD_GRAYSCALE) for y in
                         sorted(glob.glob(os.path.join("templates", "uyari", "*.png"))))
                         if img is not None]
        from dialog_cevapla import DialogCevapla
        self.dialog = DialogCevapla()
        from yeniden_baglan import Baglanti
        from biyolog import Biyolog
        from ekipman import Ekipman
        yeniden_baglan.ayarla(ayar.get("karakter", ""))
        self.baglanti = Baglanti(ayar.get("hesap", ""))
        self.biyolog = Biyolog(aktif=ayar.get("biyolog", True))
        self.ekipman = Ekipman([ad for ad in ("yuzuk", "eldiven") if ayar.get(ad, True)])
        self.sct = mss.mss()
        self.atla = []         # takılı metinler: [[x, y, bitis_zamani], ...] (ekran koordinatı)
        if kisayol:
            keyboard.add_hotkey(BASLAT_TUSU, self.degistir)
            keyboard.add_hotkey("f10", self.kapat)

    def degistir(self):
        self.calisiyor = not self.calisiyor
        print(">> BAŞLADI" if self.calisiyor else ">> DURAKLATILDI")

    def kapat(self):
        self.cikis = True

    def kare_al(self, bolge):
        return cv2.cvtColor(np.array(self.sct.grab(bolge)), cv2.COLOR_BGRA2BGR)

    def goster(self, kare, metinler, hedef=None):
        if not HATA_AYIKLAMA:
            return
        g = kare.copy()
        for x, y, s, ad in metinler:
            cv2.circle(g, (x, y), 30, (0, 255, 0), 2)
            cv2.putText(g, f"{ad} {s:.2f}", (x - 40, y + 45), 0, 0.5, (0, 255, 0), 1)
        if hedef:
            cv2.circle(g, hedef[:2], 40, (0, 0, 255), 3)
        cv2.imshow("tespit", cv2.resize(g, None, fx=0.5, fy=0.5))
        cv2.waitKey(1)

    def uyari_var(self, kare):
        """Ekranda anket sorusu gibi bir pencere var mı?"""
        if not self.uyarilar:
            return False
        gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
        return any(cv2.matchTemplate(gri, t, cv2.TM_CCOEFF_NORMED).max() >= UYARI_ESIK
                   for t in self.uyarilar)

    def uyari_metnini_oku(self, kare):
        """Doğrulama penceresindeki metni yalnızca OCR ile okur; tıklama yapmaz."""
        if pytesseract is None:
            print("   OCR kullanılamıyor: 'pip install pytesseract' kurun.")
            print("   Ayrıca Windows için Tesseract OCR uygulaması kurulu olmalı.")
            return

        try:
            # oku.py: yazı rengine göre maskeler, soru ve seçenek kutularını kendisi bulur.
            soru, secenekler = oku.coz(kare)
        except Exception as exc:
            print(f"   OCR hatası: {exc}")
            return
        if soru is None:
            print("   OCR: soru/seçenek kutuları bulunamadı.")
            return
        print("   --- OCR metni (yalnızca okuma) ---")
        print("   Soru:", soru)
        for i, s in enumerate(secenekler, 1):
            print(f"   {i}) {s}")
        print("   --------------------------------")
        return soru, secenekler

    def uyari_bekle(self, bolge):
        """Dialog gelince LLM ile cevaplamayı dener; başarısız olursa kapanana kadar bekler."""
        kare = self.kare_al(bolge)
        print("!! Doğrulama penceresi açık.")
        if pytesseract is not None:
            basarili = self.dialog.cevapla(kare, bolge)
            if basarili:
                time.sleep(1.5)
                return
            print("   LLM cevabı başarısız, manuel bekleniyor...")
        else:
            print("   Tesseract kurulu değil, manuel bekleniyor...")
        # Fallback: kapanana kadar bekle
        yok_sayac = 0
        while not self.cikis and yok_sayac < 3:
            if self.uyari_var(self.kare_al(bolge)):
                yok_sayac = 0
            else:
                yok_sayac += 1
            time.sleep(0.3)
        print("   Doğrulama penceresi kapandı, devam ediliyor.")
        time.sleep(1.0)

    def bekle(self, sure, bolge):
        """Belirtilen süre bekler; başlat/duraklat ya da F10'a basılırsa veya doğrulama penceresi çıkarsa döner."""
        bitis = time.time() + sure
        while time.time() < bitis:
            if not self.calisiyor or self.cikis:
                return False
            if self.uyari_var(self.kare_al(bolge)):
                self.uyari_bekle(bolge)
                return False
            time.sleep(0.5)
        return True

    def saldir(self, bolge, hedef):
        """Hedefe tıklar ve metin kırılana kadar başka hiçbir metine tıklamaz."""
        tikla(bolge, hedef[0], hedef[1])
        if not TAKIP_MODU:
            sure = random.uniform(*SALDIRI_SURESI)
            print(f"   {hedef[3]} tıklandı, {sure:.0f} sn bekleniyor...")
            return self.bekle(sure, bolge)

        ad = hedef[3]
        sablon = dict(self.sablonlar)[ad]
        maks = MAKS_SURE.get(ad, MAKS_SURE["varsayilan"])
        merkez = (bolge["width"] / 2, bolge["height"] / 2)
        print(f"   {ad} tıklandı, kırılana kadar takip ediliyor...")

        # Takip, gövdeyi değil üstündeki yazıyı izler.
        # Karakter yürürken kamera kaydığı için yazı da kayar: hareket yönü tahmin edilip
        # geniş alanda aranır. Karakter metne varıp durunca alan daraltılır ki metin
        # kırıldığında hemen yanındaki başka metnin yazısına atlamasın.
        yazi = (hedef[0], hedef[1] - ISIM_GOVDE_FARKI)
        vx = vy = 0.0          # son karedeki kayma (piksel)
        varildi = False
        sabit_sayac = 0
        govde = hedef[:2]
        tekrar_tiklama = 0
        baslangic = son_gorulme = son_tik = time.time()

        while self.calisiyor and not self.cikis:
            simdi = time.time()
            if simdi - baslangic > maks:
                self.atla_ekle(govde, f"{maks} sn doldu")
                return False

            kare = self.kare_al(bolge)
            if self.uyari_var(kare):
                self.uyari_bekle(bolge)
                return False  # ana döngü en yakın metni yeniden bulup tıklar
            gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
            tahmin = (yazi[0] + vx, yazi[1] + vy)
            yaricap = 20.0 if varildi else 150.0
            bulunan = isim_ara(gri, sablon, tahmin, yaricap)

            if bulunan:
                vx, vy = bulunan[0] - yazi[0], bulunan[1] - yazi[1]
                self.atla_kaydir(vx, vy)
                yazi = bulunan
                son_gorulme = simdi
                govde = (int(yazi[0]), int(yazi[1] + ISIM_GOVDE_FARKI))
                uzaklik = ((govde[0] - merkez[0]) ** 2 + (govde[1] - merkez[1]) ** 2) ** 0.5
                hareket = (vx * vx + vy * vy) ** 0.5
                if hareket < 4:   # ekran kaymıyor = karakter durdu
                    sabit_sayac += 1
                    varildi = varildi or sabit_sayac >= 3
                else:
                    sabit_sayac = 0
                    if hareket > 8:   # karakter yeniden yürümeye başladı
                        varildi = False
                # Karakter uzun süredir metne ulaşamadıysa (tıklama boşa gittiyse) tekrar tıkla
                if uzaklik > ULASTI_YARICAP and simdi - son_tik > YENIDEN_TIKLA_SURESI:
                    if tekrar_tiklama >= ULASAMAZSA_TIKLAMA:
                        self.atla_ekle(govde, "karakter ulaşamıyor")
                        return False
                    tekrar_tiklama += 1
                    print(f"   Karakter metne ulaşmadı, tekrar tıklanıyor ({tekrar_tiklama}/{ULASAMAZSA_TIKLAMA}).")
                    tikla(bolge, *govde)
                    son_tik = simdi
                self.goster(kare, [(*govde, 1.0, ad)], (*govde,))
            elif simdi - son_gorulme > KAYIP_SURESI:
                print(f"   Metin kırıldı ({simdi - baslangic:.0f} sn).")
                return True

            time.sleep(0.1)
        return False

    def atla_ekle(self, govde, sebep):
        print(f"   Metin takılı ({sebep}), {ATLA_SURESI} sn boyunca atlanacak.")
        self.atla.append([float(govde[0]), float(govde[1]), time.time() + ATLA_SURESI])

    def atla_kaydir(self, dx, dy):
        """Karakter yürüyünce kamera kayar; atlanan metinlerin ekran konumlarını da kaydır."""
        for a in self.atla:
            a[0] += dx
            a[1] += dy

    def atlananlari_cikar(self, metinler):
        simdi = time.time()
        self.atla = [a for a in self.atla if a[2] > simdi]
        return [m for m in metinler
                if all((m[0] - a[0]) ** 2 + (m[1] - a[1]) ** 2 > ATLA_YARICAP ** 2 for a in self.atla)]

    def topla(self):
        if TOPLAMA_TUSU:
            for _ in range(TOPLAMA_SAYISI):
                pydirectinput.press(TOPLAMA_TUSU)
                time.sleep(0.1)

    def calistir(self):
        adlar = ", ".join(ad for ad, _ in self.sablonlar)
        print(f"Aranan metinler: {adlar}")
        print(f"'{BASLAT_TUSU}' = başlat/duraklat, F10 = çıkış")
        kirildi = None   # son metnin kırıldığı an (geçiş süresini ölçmek için)
        while not self.cikis:
            if not self.calisiyor:
                time.sleep(0.1)
                continue
            if self.baglanti.kopuk_mu():
                self.baglanti.baglan(lambda: self.calisiyor and not self.cikis)
                continue
            if self.biyolog.zamani_geldi():
                self.biyolog.calistir(self.kare_al, oyun_bolgesi())
                continue
            if self.ekipman.zamani_geldi():
                self.ekipman.calistir(self.kare_al, oyun_bolgesi())
            bolge = oyun_bolgesi()
            kare = self.kare_al(bolge)
            if self.uyari_var(kare):
                self.uyari_bekle(bolge)
                continue
            metinler = self.atlananlari_cikar(metinleri_bul(kare, self.sablonlar))
            if not metinler:
                self.goster(kare, metinler)
                if KAMERA_DONDUR_TUSU:
                    pydirectinput.keyDown(KAMERA_DONDUR_TUSU)
                    time.sleep(0.4)
                    pydirectinput.keyUp(KAMERA_DONDUR_TUSU)
                time.sleep(0.3)
                continue
            hedef = en_yakin(metinler, (bolge["width"] // 2, bolge["height"] // 2))
            self.goster(kare, metinler, hedef)
            if kirildi:
                print(f"   Sonraki metne geçiş: {time.time() - kirildi:.1f} sn")
                kirildi = None
            if self.saldir(bolge, hedef):
                self.topla()
                kirildi = time.time()
        print("Çıkılıyor.")


if __name__ == "__main__":
    Bot().calistir()
