@echo off
:: Run PhantomGPS as Administrator
powershell -Command "Start-Process 'py' '-3.12 C:\Users\damian\Desktop\files\main.py' -Verb RunAs"
