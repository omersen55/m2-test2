@echo off
rem BotHesabi oturumunda bir kez calistir: Python paketlerini kontrol eder ve ekrani gosterir.
cd /d C:\m2-bot
python -m pip install -r requirements.txt
echo.
python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); u=ctypes.windll.user32; print('Ekran:', u.GetSystemMetrics(0), 'x', u.GetSystemMetrics(1), '  Olcek: %%', u.GetDpiForSystem()*100//96)"
python -c "import cv2, mss, pydirectinput, keyboard, pytesseract, requests; print('Paketler: TAMAM')"
echo.
pause
