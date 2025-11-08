@echo off
chcp 65001 >nul
title Iniciador do Agente Local
color 0A

echo =============================================
echo     SELECIONE O NAVEGADOR PARA DEPURAÇÃO
echo =============================================
echo 1 - Opera GX
echo 2 - Google Chrome
echo 3 - Microsoft Edge
echo.
set /p B="Digite 1, 2 ou 3 e tecle ENTER: "

rem ==== Caminhos dos navegadores ====
set "OPERA_PATH=C:\Users\Administrator\AppData\Local\Programs\Opera GX\opera.exe"
set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "EDGE_PATH=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

rem ==== Cria pastas temporárias ====
set "TMP_PROFILE=%~dp0browser_profile"
if not exist "%TMP_PROFILE%" mkdir "%TMP_PROFILE%"

if "%B%"=="1" (
    set "BROWSER=OPERA"
    set "BINARY=%OPERA_PATH%"
    set "USERDATA=%TMP_PROFILE%\opera"
    set "DRIVER=chromedriver.exe"
) else if "%B%"=="2" (
    set "BROWSER=CHROME"
    set "BINARY=%CHROME_PATH%"
    set "USERDATA=%TMP_PROFILE%\chrome"
    set "DRIVER=chromedriver.exe"
) else if "%B%"=="3" (
    set "BROWSER=EDGE"
    set "BINARY=%EDGE_PATH%"
    set "USERDATA=%TMP_PROFILE%\edge"
    set "DRIVER=msedgedriver.exe"
) else (
    echo.
    echo ❌ Opcao invalida.
    pause
    exit /b 1
)

rem ==== Verifica se o driver existe ====
if not exist "%~dp0%DRIVER%" (
    echo.
    echo ❌ ERRO: O driver %DRIVER% nao foi encontrado na pasta:
    echo %~dp0
    echo.
    echo Coloque o arquivo %DRIVER% na mesma pasta deste .bat
    pause
    exit /b 1
)

rem ==== Cria perfil se nao existir ====
if not exist "%USERDATA%" mkdir "%USERDATA%"

rem ==== Inicia o navegador ====
echo.
echo 🚀 Abrindo %BROWSER% com porta de depuração 9222...
start "" "%BINARY%" --remote-debugging-port=9222 --user-data-dir="%USERDATA%" --start-maximized

rem ==== Espera o navegador abrir ====
timeout /t 5 /nobreak >nul

rem ==== Executa o agente local ====
echo.
echo 🧠 Iniciando agente_local.py (navegador: %BROWSER%)...
echo =============================================
python agente_local.py %BROWSER%

pause
