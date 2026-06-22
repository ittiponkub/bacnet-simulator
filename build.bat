@echo off
echo ========================================
echo  BACnet Simulator - Build Installer
echo ========================================
echo.

:: Activate venv
call venv\Scripts\activate

:: Build with PyInstaller
echo Building with PyInstaller...
pyinstaller bacnet_sim.spec --clean --noconfirm

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo.
echo ========================================
echo  BUILD SUCCESS!
echo ========================================
echo.
echo Output: dist\BACnetSimulator\
echo Run:    dist\BACnetSimulator\BACnetSimulator.exe
echo.
echo To distribute: zip the dist\BACnetSimulator folder
echo Target machine only needs Edge WebView2 Runtime
echo (pre-installed on Windows 10/11)
echo ========================================
pause
