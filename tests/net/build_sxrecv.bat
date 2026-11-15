@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cd /d "%~dp0"
if not exist out\sxrecv mkdir out\sxrecv
cl /nologo /std:c++20 /EHsc /O2 /W3 /MD /I..\..\src /Foout\sxrecv\ /Feout\test_sxrecv.exe test_sxrecv.cpp ..\..\src\s2r_net.cpp ws2_32.lib || exit /b 1
out\test_sxrecv.exe
exit /b %errorlevel%
