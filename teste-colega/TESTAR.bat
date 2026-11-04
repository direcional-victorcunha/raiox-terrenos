@echo off
rem Teste de compatibilidade do PC para o Raio-X. Nao instala nada.
rem Clique duas vezes. No fim, mande o arquivo resultado-teste.txt (mesma pasta) de volta.
cd /d "%~dp0"
echo Testando este PC (leva ate 2 minutos)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0teste.ps1"
if errorlevel 1 (
  echo.
  echo O PowerShell em arquivo foi bloqueado; tentando de outro jeito...
  powershell -NoProfile -Command "Get-Content -Raw '%~dp0teste.ps1' | Invoke-Expression"
)
echo.
pause
