"""
Doğrulama dialog modülü.

Kullanım (bot_ocr.py içinden):
    from dialog_cevapla import DialogCevapla
    dc = DialogCevapla()
    dc.cevapla(kare, bolge)
"""
import json
import os
import re
import time
from datetime import datetime

import cv2
import numpy as np
import pydirectinput
import requests

import oku

# Tesseract kurulum yolu — gerekirse değiştir
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
LLM_SAGLAYICI = "gemini"     # "gemini" (Google API) veya "ollama" (yerel model)
GEMINI_MODEL  = "gemini-flash-lite-latest"   # ~1 sn. "gemini-flash-latest" sık sık aşırı yüklü (503/zaman aşımı).
GEMINI_TIMEOUT = 10          # sn
GEMINI_YEDEK_OLLAMA = True   # Gemini hata verirse (kota/yoğunluk/internet) yerel Ollama modeline sor.
# API anahtarı koda yazılmaz: GEMINI_API_KEY ortam değişkeni ya da bu dosyanın yanındaki gemini_key.txt
GEMINI_KEY_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_key.txt")
OLLAMA_URL   = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:3b"
# Karşılaşılan sorular buraya kaydedilir (resimler/ + sorular.jsonl).
# Bot hangi klasörden çalıştırılırsa çalıştırılsın bu dosyanın yanındaki veriseti/ kullanılır.
VERISETI_KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veriseti")
OLLAMA_TIMEOUT = 60         # sn — ilk soruda model RAM'e yükleniyor, uzun tutuldu

# Dialog layout — başlık şablonuna göre rölatif ofsetler (piksel)
# Bunları kendi çözünürlüğüne göre ayarlayabilirsin.
BASLIK_SABLON = "templates/uyari/oyunanketi.png"
SORU_OFSET_Y  = -30          # başlık tepesinden soruya
SORU_YUKSEK   = 40
SIKU_OFSET_Y  = 130          # başlık tepesinden şıklara
SIKU_YUKSEK   = 58
SIKU_SOL_PAD  = -165         # başlık sol kenarından şık alanı sol kenarına
SIKU_SAG_PAD  = 205          # başlık sağ kenarından şık alanı sağ kenarına
DIALOG_SOL    = -170         # başlık sol kenarından OCR alanı sol kenarına
DIALOG_SAG    = 170          # başlık sağ kenarından OCR alanı sağ kenarına
DIALOG_UST    = 24           # başlık tepesinden OCR alanı üstüne. Başlık çubuğu (~0-20 px) dışarıda
                             # kalsın; yoksa "Güvenlik Doğrulaması" soru diye okunuyor.
DIALOG_ALT    = 300          # başlık tepesinden OCR alanı altına
MIN_SIK_GENIS = 30          # px — bu genişlikten dar kutuları atla
# ------------------------------------------------------------------------


def _gemini_anahtari() -> str:
    anahtar = os.environ.get("GEMINI_API_KEY", "").strip()
    if not anahtar and os.path.exists(GEMINI_KEY_DOSYA):
        with open(GEMINI_KEY_DOSYA, encoding="utf-8") as f:
            anahtar = f.read().strip()
    if not anahtar:
        raise RuntimeError("Gemini API anahtarı yok (GEMINI_API_KEY ya da gemini_key.txt).")
    return anahtar


def _model_adi() -> str:
    return GEMINI_MODEL if LLM_SAGLAYICI == "gemini" else OLLAMA_MODEL


def _llm_sor(prompt: str) -> str:
    if LLM_SAGLAYICI == "gemini":
        try:
            return _gemini_sor(prompt)
        except Exception as exc:
            if not GEMINI_YEDEK_OLLAMA:
                raise
            print(f"   Gemini hatası ({str(exc)[:80]}), Ollama'ya soruluyor...")
    return _ollama_sor(prompt)


def _gemini_sor(prompt: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": _gemini_anahtari()},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=GEMINI_TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")
    parcalar = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parcalar if not p.get("thought")).strip()


def _ollama_sor(prompt: str) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
              "options": {"temperature": 0}},   # aynı soruya hep aynı cevap
        timeout=OLLAMA_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["response"].strip()


def _ocr(gri_crop) -> str:
    """Gri bir crop'tan metin okur (pytesseract zorunlu değil)."""
    try:
        import pytesseract
        buyuk = cv2.resize(gri_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        _, th  = cv2.threshold(buyuk, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        metin  = pytesseract.image_to_string(th, config="--oem 0 --psm 7 -c tessedit_char_blacklist=|").strip()
        return metin
    except Exception:
        return ""


def _gradient_sik_sinirlari(gri_satir):
    """Yatay Sobel gradyanından şık kutu sınırlarını döndürür → [(x_sol, x_sag), ...]"""
    grad   = np.abs(cv2.Sobel(gri_satir.astype(float), cv2.CV_64F, 1, 0))
    proj   = grad.mean(axis=0)
    esik   = proj.max() * 0.30
    peaks  = np.where(proj > esik)[0]
    if len(peaks) == 0:
        return []
    # Ardışık pikleri grupla
    gruplar, grup = [], [peaks[0]]
    for p in peaks[1:]:
        if p - grup[-1] <= 5:
            grup.append(p)
        else:
            gruplar.append(grup)
            grup = [p]
    gruplar.append(grup)
    sinirlar = [int(np.mean(g)) for g in gruplar]
    # Komşu sınır çiftleri arasındaki aralık = kutu
    kutular = []
    for i in range(len(sinirlar) - 1):
        sol, sag = sinirlar[i], sinirlar[i + 1]
        if sag - sol >= MIN_SIK_GENIS:
            kutular.append((sol, sag))
    return kutular


def _dialog_konumu(kare):
    """Başlık şablonunu eşleştirerek dialog başlığının (tx, ty, tw, th) değerlerini döndürür."""
    t = cv2.imread(BASLIK_SABLON, cv2.IMREAD_GRAYSCALE)
    if t is None:
        return None
    gri = cv2.cvtColor(kare, cv2.COLOR_BGR2GRAY)
    sonuc = cv2.matchTemplate(gri, t, cv2.TM_CCOEFF_NORMED)
    _, skor, _, (tx, ty) = cv2.minMaxLoc(sonuc)
    if skor < 0.75:
        return None
    th2, tw2 = t.shape[:2]
    return tx, ty, tw2, th2


class DialogCevapla:
    def __init__(self):
        self._sablon_mevcut = cv2.imread(BASLIK_SABLON) is not None
        if not self._sablon_mevcut:
            print("[DialogCevapla] UYARI: Başlık şablonu bulunamadı:", BASLIK_SABLON)

    # ------------------------------------------------------------------ Ana API
    def cevapla(self, kare, bolge) -> bool:
        """
        Ekran karesinde doğrulama dialogu varsa:
          1. Soruyu + şıkları OCR ile oku
          2. LLM'e gönder
          3. Cevabı şıklarla eşleştir
          4. Doğru şıka tıkla
        Başarılı ise True döner.
        """
        # oku.py: yazı rengine göre soru ve şık kutularını bulup okur
        # Tüm kareyi değil yalnızca dialogu ver; yoksa üstteki HUD/buff çubuğu "şık" sanılıyor.
        konum = _dialog_konumu(kare)
        if konum is None:
            print("   Dialog başlığı bulunamadı, atlanıyor.")
            return False
        tx, ty, tw, _ = konum
        ox, oy = max(0, tx + DIALOG_SOL), max(0, ty + DIALOG_UST)
        crop = kare[oy:ty + DIALOG_ALT, ox:min(kare.shape[1], tx + tw + DIALOG_SAG)]
        cv2.imwrite("debug_dialog.png", crop)   # OCR'a giden alanı kontrol etmek için
        try:
            soru_metni, metinler, kutular = oku.coz_kutulu(crop)
        except Exception as exc:
            print(f"   OCR hatası: {exc}")
            return False
        if soru_metni is None:
            print("   Şık kutuları tespit edilemedi, atlanıyor.")
            return False
        kutular = [(x + ox, y + oy, w, h) for x, y, w, h in kutular]
        soru_metni = soru_metni or "(soru okunamadı)"
        print(f"   Soru OCR: {soru_metni!r}")

        siklar = []   # [(metin, ekran_x, ekran_y), ...]
        for metin, (x, y, w, h) in zip(metinler, kutular):
            ekran_cx = bolge["left"] + int(x + w / 2)
            ekran_cy = bolge["top"]  + int(y + h / 2)
            siklar.append((metin, ekran_cx, ekran_cy))
            print(f"     Şık OCR: {metin!r}  @ ekran({ekran_cx},{ekran_cy})")

        if not any(s[0] for s in siklar):
            print("   Hiçbir şık metni okunamadı.")
            return False

        # ---- LLM'e sor: şıklar numaralı, cevap yalnızca numara ----
        # Numaralar siklar listesiyle birebir; okunamayan şık da numarasını korur.
        prompt = _prompt(soru_metni, [s[0] for s in siklar])
        print("   LLM'e soruluyor...")
        try:
            llm_cevap = _llm_sor(prompt)
        except Exception as exc:
            print(f"   LLM hatası: {exc}")
            _kaydet(crop, soru_metni, siklar, None, None)
            return False
        print(f"   LLM cevabı: {llm_cevap!r}")

        # ---- Cevaptaki ilk sayıyı şık numarası olarak al ----
        m = re.search(r"\d+", llm_cevap)
        no = int(m.group()) if m else 0
        if not 1 <= no <= len(siklar):
            print("   Geçerli bir şık numarası dönmedi, atlanıyor.")
            _kaydet(crop, soru_metni, siklar, llm_cevap, None)
            return False

        _kaydet(crop, soru_metni, siklar, llm_cevap, no)
        return _tikla(siklar, no)


def _prompt(soru_metni, metinler) -> str:
    # Numaralar ekrandaki kutularla birebir; okunamayan şık da numarasını korur.
    numarali = "\n".join(f"{i}) {m or '(okunamadı)'}" for i, m in enumerate(metinler, 1))
    return (
        "Bir oyundaki doğrulama sorusunu cevaplıyorsun.\n"
        "Soru ve şıklar ekrandan okundu; bazı harfler rakamla yer değiştirmiş olabilir "
        "(örn. 4=a, 3=e, 1=i, 0=o) ya da araya fazladan karakter girmiş olabilir. "
        "Önce sorunun ne demek istediğini anla.\n\n"
        f"Soru: {soru_metni}\n"
        f"Şıklar:\n{numarali}\n\n"
        f"Doğru şıkkın SADECE numarasını yaz (1-{len(metinler)}). Başka hiçbir şey yazma."
    )


def _kaydet(crop, soru, siklar, llm_cevap, no):
    """Karşılaşılan soruyu veri setine ekler: dialog görüntüsü + sorular.jsonl'a bir satır.
    'dogru' alanı boş kalır; cevabın doğruluğu sonradan elle işaretlenebilir."""
    try:
        zaman = datetime.now()
        ad = zaman.strftime("%Y%m%d_%H%M%S_%f")
        os.makedirs(os.path.join(VERISETI_KLASOR, "resimler"), exist_ok=True)
        resim = f"resimler/{ad}.png"
        cv2.imwrite(os.path.join(VERISETI_KLASOR, resim), crop)
        kayit = {
            "zaman": zaman.isoformat(timespec="seconds"),
            "resim": resim,
            "soru": soru,
            "siklar": [s[0] for s in siklar],
            "model": _model_adi(),
            "llm_cevap": llm_cevap,
            "secilen_no": no,
            "secilen": siklar[no - 1][0] if no else None,
            "dogru": None,
        }
        with open(os.path.join(VERISETI_KLASOR, "sorular.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"   Veri seti kaydı başarısız: {exc}")


def _tikla(siklar, no) -> bool:
    secilen, ekran_x, ekran_y = siklar[no - 1]
    print(f"   Seçilen: {no}) {secilen!r} -> tıklanıyor ({ekran_x},{ekran_y})")
    pydirectinput.moveTo(ekran_x, ekran_y)
    time.sleep(0.05)
    pydirectinput.click()
    return True


# ------------------------------------------------------------------ Test
if __name__ == "__main__":
    import sys
    img_yol = sys.argv[1] if len(sys.argv) > 1 else "ornek4.png"
    kare = cv2.imread(img_yol)
    bolge = {"left": 0, "top": 0, "width": kare.shape[1], "height": kare.shape[0]}
    dc = DialogCevapla()

    # Tıklamayı simüle et (gerçek tıklama yapma)
    pydirectinput.moveTo = lambda x, y: print(f"  [SIM] moveTo({x},{y})")
    pydirectinput.click  = lambda: print(f"  [SIM] click()")

    print("=== Dialog testi ===")
    sonuc = dc.cevapla(kare, bolge)
    print("Sonuç:", "BAŞARILI" if sonuc else "BAŞARISIZ")
