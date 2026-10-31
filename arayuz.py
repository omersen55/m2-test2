"""
Botun basit kontrol paneli.

Karakter adı  -> hangi oyun penceresinin kullanılacağı ("REDIS" yazılırsa "REDIS - Farm2").
Hesap adı     -> oyundan atılınca giriş ekranında tıklanacak kayıtlı hesap ("uolo2" gibi).
Mod, biyolog / tecrübe yüzüğü / hırsız eldiveni seçimleri ve Başlat.
'-' tuşu duraklat/devam, F10 durdur. Log, "Log" düğmesine basınca açılır.

Ayarlar ayarlar.json dosyasına kaydedilir, bir sonraki açılışta hatırlanır.
Çalıştırma: Bot Paneli.bat  (ya da: python arayuz.py)
"""
import ctypes
import json
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import scrolledtext, ttk

KLASOR = os.path.dirname(os.path.abspath(__file__))
os.chdir(KLASOR)                   # templates/ göreli yolları için

# Oyun yönetici olarak çalıştığı için bot da yönetici olmalı; yoksa Windows tuş ve tıklamaları
# oyuna iletmez (bot ekranı görür ama vuramaz). Yönetici değilsek kendimizi yönetici olarak açarız.
if not ctypes.windll.shell32.IsUserAnAdmin():
    sonuc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{os.path.abspath(__file__)}"', KLASOR, 1)
    if sonuc > 32:                 # yeni (yönetici) pencere açıldı
        sys.exit(0)
    # Kullanıcı UAC'yi reddettiyse normal yetkiyle devam (log'da uyarı çıkar).

AYAR_DOSYA = "ayarlar.json"
LOG_DOSYA = "bot_log.txt"
VARSAYILAN = {"karakter": "", "hesap": "", "mod": "metin",
              "biyolog": True, "yuzuk": True, "eldiven": True}
LOG_SATIR = 2000                   # log penceresinde tutulacak en fazla satır


class Yazici:
    """print() çıktılarını log penceresine ve bot_log.txt dosyasına aktarır
    (bot başka bir iş parçacığında yazar)."""

    def __init__(self, kuyruk):
        self.kuyruk = kuyruk
        self.kilit = threading.Lock()
        self.satir_basi = True
        try:
            self.dosya = open(LOG_DOSYA, "a", encoding="utf-8")
        except OSError:
            self.dosya = None

    def write(self, metin):
        if not metin:
            return
        self.kuyruk.put(metin)
        if self.dosya:
            with self.kilit:
                for parca in metin.splitlines(keepends=True):
                    if self.satir_basi:
                        self.dosya.write(time.strftime("%H:%M:%S "))
                    self.dosya.write(parca)
                    self.satir_basi = parca.endswith("\n")
                self.dosya.flush()

    def flush(self):
        pass


log_kuyrugu = queue.Queue()
sys.stdout = sys.stderr = Yazici(log_kuyrugu)

# Bot modülleri stdout yönlendirildikten sonra yüklensin ki ilk mesajlar da loga düşsün.
try:
    import keyboard

    import bot_ocr
    import zindan
    YUKLEME_HATASI = None
except Exception:
    YUKLEME_HATASI = traceback.format_exc()


def ayarlari_oku():
    try:
        with open(AYAR_DOSYA, encoding="utf-8") as f:
            return {**VARSAYILAN, **json.load(f)}
    except (OSError, ValueError):
        return dict(VARSAYILAN)


def ayarlari_yaz(ayar):
    try:
        with open(AYAR_DOSYA, "w", encoding="utf-8") as f:
            json.dump(ayar, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"Ayarlar kaydedilemedi: {exc}")


class Panel:
    def __init__(self, kok):
        self.kok = kok
        self.bot = None
        self.is_parcacigi = None
        kok.title("Farm2 Bot")
        kok.resizable(False, False)
        kok.protocol("WM_DELETE_WINDOW", self.kapat)

        ayar = ayarlari_oku()
        self.karakter = tk.StringVar(value=ayar["karakter"])
        self.hesap = tk.StringVar(value=ayar["hesap"])
        self.mod = tk.StringVar(value=ayar["mod"])
        self.biyolog = tk.BooleanVar(value=ayar["biyolog"])
        self.yuzuk = tk.BooleanVar(value=ayar["yuzuk"])
        self.eldiven = tk.BooleanVar(value=ayar["eldiven"])

        govde = ttk.Frame(kok, padding=12)
        govde.pack(fill="both", expand=True)

        ayarlar = ttk.LabelFrame(govde, text="Hesap", padding=8)
        ayarlar.pack(fill="x")
        ttk.Label(ayarlar, text="Karakter adı").grid(row=0, column=0, sticky="w", pady=2)
        self.karakter_kutu = ttk.Entry(ayarlar, textvariable=self.karakter, width=24)
        self.karakter_kutu.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)
        ttk.Label(ayarlar, text="Hesap adı").grid(row=1, column=0, sticky="w", pady=2)
        self.hesap_kutu = ttk.Entry(ayarlar, textvariable=self.hesap, width=24)
        self.hesap_kutu.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)
        ttk.Label(ayarlar, text="Pencere: \"<karakter> - Farm2\"   Hesap: girişteki kayıtlı buton",
                  foreground="#777").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        secenek = ttk.LabelFrame(govde, text="Seçenekler", padding=8)
        secenek.pack(fill="x", pady=(10, 0))
        mod = ttk.Frame(secenek)
        mod.pack(fill="x")
        ttk.Label(mod, text="Mod:").pack(side="left")
        self.mod_dugmeleri = [
            ttk.Radiobutton(mod, text="Metin kesme", variable=self.mod, value="metin"),
            ttk.Radiobutton(mod, text="Örümcek zindanı", variable=self.mod, value="zindan"),
        ]
        for d in self.mod_dugmeleri:
            d.pack(side="left", padx=(8, 0))
        self.kutular = [
            ttk.Checkbutton(secenek, text="Biyolog ver (3 dk'da bir)", variable=self.biyolog),
            ttk.Checkbutton(secenek, text="Tecrübe yüzüğü tak", variable=self.yuzuk),
            ttk.Checkbutton(secenek, text="Hırsız eldiveni tak", variable=self.eldiven),
        ]
        for k in self.kutular:
            k.pack(anchor="w", pady=(4, 0))

        dugmeler = ttk.Frame(govde)
        dugmeler.pack(fill="x", pady=(12, 0))
        self.baslat_dugme = ttk.Button(dugmeler, text="Başlat", command=self.baslat)
        self.baslat_dugme.pack(side="left", expand=True, fill="x")
        self.durdur_dugme = ttk.Button(dugmeler, text="Durdur", command=self.durdur, state="disabled")
        self.durdur_dugme.pack(side="left", expand=True, fill="x", padx=(8, 0))

        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=(10, 0))
        self.durum = ttk.Label(alt, text="Durduruldu", foreground="#a00")
        self.durum.pack(side="left")
        self.log_dugme = ttk.Button(alt, text="Log ▸", width=8, command=self.log_ac_kapa)
        self.log_dugme.pack(side="right")
        ttk.Label(govde, text="'-' = duraklat / devam     F10 = durdur",
                  foreground="#777").pack(anchor="w", pady=(6, 0))

        self.log_cerceve = ttk.Frame(govde)
        self.log = scrolledtext.ScrolledText(self.log_cerceve, width=70, height=18,
                                             font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log_acik = False

        if YUKLEME_HATASI:
            print("Bot modülleri yüklenemedi:\n" + YUKLEME_HATASI)
            self.baslat_dugme.configure(state="disabled")
            self.log_ac_kapa()
        else:
            keyboard.add_hotkey(bot_ocr.BASLAT_TUSU, self.duraklat_devam)
            keyboard.add_hotkey("f10", self.durdur)
        print(f"===== Panel açıldı {time.strftime('%d.%m.%Y %H:%M')} "
              f"(yönetici: {'evet' if ctypes.windll.shell32.IsUserAnAdmin() else 'HAYIR'})")
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("UYARI: Panel yönetici değil; oyun yönetici olarak açıksa tuş ve tıklamalar oyuna gitmez.")
        self.kilitli = False
        self.guncelle()

    # ------------------------------------------------------------ düğmeler
    def ayar(self):
        return {"karakter": self.karakter.get().strip(), "hesap": self.hesap.get().strip(),
                "mod": self.mod.get(), "biyolog": self.biyolog.get(),
                "yuzuk": self.yuzuk.get(), "eldiven": self.eldiven.get()}

    def baslat(self):
        if self.bot:                     # çalışıyorsa bu düğme duraklat/devam
            self.duraklat_devam()
            return
        ayar = self.ayar()
        ayarlari_yaz(ayar)
        if not ayar["karakter"]:
            print("Karakter adı boş: ilk bulunan oyun penceresi kullanılacak.")
        if not ayar["hesap"]:
            print("Hesap adı boş: yeniden bağlanırken templates/giris/uolo2.png tıklanacak.")
        self.ayarlar_kilit(True)
        self.is_parcacigi = threading.Thread(target=self.calistir, args=(ayar,), daemon=True)
        self.is_parcacigi.start()

    def calistir(self, ayar):
        sinif = zindan.Zindan if ayar["mod"] == "zindan" else bot_ocr.Bot
        try:
            self.bot = sinif(ayar, kisayol=False)
            print(f">> {ayar['karakter'] or 'oyun'} için bot başlıyor (hesap: {ayar['hesap'] or '-'}).")
            self.bot.calisiyor = True
            self.bot.calistir()
        except SystemExit as exc:
            print(f"Bot durdu: {exc}")
        except Exception:
            print("Bot hata verdi:\n" + traceback.format_exc())
        finally:
            self.bot = None
            print(">> Bot durdu.")
            # Kilidi guncelle() açar: tkinter'a bu iş parçacığından dokunulmaz.

    def duraklat_devam(self):
        if self.bot:
            self.bot.degistir()

    def durdur(self):
        if self.bot:
            print(">> Durduruluyor...")
            self.bot.cikis = True

    def kapat(self):
        self.durdur()
        if self.is_parcacigi and self.is_parcacigi.is_alive():
            self.is_parcacigi.join(timeout=3)
        self.kok.destroy()

    def ayarlar_kilit(self, kilitli):
        self.kilitli = kilitli
        durum = "disabled" if kilitli else "normal"
        for w in (self.karakter_kutu, self.hesap_kutu, *self.mod_dugmeleri, *self.kutular):
            w.configure(state=durum)
        self.durdur_dugme.configure(state="normal" if kilitli else "disabled")

    def log_ac_kapa(self):
        self.log_acik = not self.log_acik
        if self.log_acik:
            self.log_cerceve.pack(fill="both", expand=True, pady=(10, 0))
            self.log_dugme.configure(text="Log ▾")
            self.log.see("end")
        else:
            self.log_cerceve.pack_forget()
            self.log_dugme.configure(text="Log ▸")
        self.kok.geometry("")            # pencere boyu içeriğe göre yeniden ayarlansın

    # ------------------------------------------------------------ periyodik
    def guncelle(self):
        parcalar = []
        while True:
            try:
                parcalar.append(log_kuyrugu.get_nowait())
            except queue.Empty:
                break
        if parcalar:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(parcalar))
            fazla = int(self.log.index("end-1c").split(".")[0]) - LOG_SATIR
            if fazla > 0:
                self.log.delete("1.0", f"{fazla + 1}.0")
            self.log.configure(state="disabled")
            self.log.see("end")

        calisan = self.is_parcacigi is not None and self.is_parcacigi.is_alive()
        if self.kilitli and not calisan:
            self.ayarlar_kilit(False)
        if self.bot is None:
            metin, renk = ("Başlatılıyor..." if calisan else "Durduruldu"), "#a00"
            dugme = "Başlat"
        elif self.bot.calisiyor:
            metin, renk, dugme = "Çalışıyor", "#080", "Duraklat"
        else:
            metin, renk, dugme = "Duraklatıldı", "#b70", "Devam"
        self.durum.configure(text=metin, foreground=renk)
        self.baslat_dugme.configure(text=dugme)
        self.kok.after(200, self.guncelle)


if __name__ == "__main__":
    kok = tk.Tk()
    Panel(kok)
    kok.mainloop()
