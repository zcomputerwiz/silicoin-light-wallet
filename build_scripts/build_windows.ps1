# $env:path should contain a path to editbin.exe and signtool.exe

$ErrorActionPreference = "Stop"

mkdir build_scripts\win_build
Set-Location -Path ".\build_scripts\win_build" -PassThru

git status

Write-Output "   ---"
Write-Output "curl miniupnpc"
Write-Output "   ---"
Invoke-WebRequest -Uri "https://pypi.chia.net/simple/miniupnpc/miniupnpc-2.2.2-cp39-cp39-win_amd64.whl" -OutFile "miniupnpc-2.2.2-cp39-cp39-win_amd64.whl"
Write-Output "Using win_amd64 python 3.9 wheel from https://github.com/miniupnp/miniupnp/pull/475 (2.2.0-RC1)"
Write-Output "Actual build from https://github.com/miniupnp/miniupnp/commit/7783ac1545f70e3341da5866069bde88244dd848"
If ($LastExitCode -gt 0){
    Throw "Failed to download miniupnpc!"
}
else
{
    Set-Location -Path - -PassThru
    Write-Output "miniupnpc download successful."
}

Write-Output "   ---"
Write-Output "Create venv - python3.9 is required in PATH"
Write-Output "   ---"
python -m venv venv
. .\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install wheel pep517
pip install pywin32
pip install pyinstaller==4.5
pip install setuptools_scm

Write-Output "   ---"
Write-Output "Get SILICOIN_INSTALLER_VERSION"
# The environment variable SILICOIN_INSTALLER_VERSION needs to be defined
$env:SILICOIN_INSTALLER_VERSION = python .\build_scripts\installer-version.py -win

if (-not (Test-Path env:SILICOIN_INSTALLER_VERSION)) {
  $env:SILICOIN_INSTALLER_VERSION = '0.0.0'
  Write-Output "WARNING: No environment variable SILICOIN_INSTALLER_VERSION set. Using 0.0.0"
  }
Write-Output "Silicoin Version is: $env:SILICOIN_INSTALLER_VERSION"
Write-Output "   ---"

Write-Output "   ---"
Write-Output "Build silicoin-blockchain wheels"
Write-Output "   ---"
pip wheel --use-pep517 --extra-index-url https://pypi.chia.net/simple/ -f . --wheel-dir=.\build_scripts\win_build .

Write-Output "   ---"
Write-Output "Install silicoin-blockchain wheels into venv with pip"
Write-Output "   ---"

Write-Output "pip install miniupnpc"
Set-Location -Path ".\build_scripts" -PassThru
pip install --no-index --find-links=.\win_build\ miniupnpc
# Write-Output "pip install setproctitle"
# pip install setproctitle==1.2.2

Write-Output "pip install silicoin-blockchain"
pip install --no-index --find-links=.\win_build\ silicoin-blockchain

Write-Output "   ---"
Write-Output "Use pyinstaller to create silicoin .exe's"
Write-Output "   ---"
$SPEC_FILE = (python -c 'import silicoin; print(silicoin.PYINSTALLER_SPEC_PATH)') -join "`n"
pyinstaller --log-level INFO $SPEC_FILE

Write-Output "   ---"
Write-Output "Copy silicoin executables to silicoin-light-gui\"
Write-Output "   ---"
Copy-Item "dist\daemon" -Destination "..\silicoin-light-gui\packages\wallet" -Recurse
Set-Location -Path "..\silicoin-light-gui" -PassThru
# We need the code sign cert in the gui subdirectory so we can actually sign the UI package
# If ($env:HAS_SECRET) {
#     Copy-Item "win_code_sign_cert.p12" -Destination "packages\gui\"
# }

git status

Write-Output "   ---"
Write-Output "Prepare Electron packager"
Write-Output "   ---"
$Env:NODE_OPTIONS = "--max-old-space-size=3000"
npm install -g electron-winstaller
npm install -g electron-packager
npm install -g lerna

lerna clean -y
npm install

git status

Write-Output "   ---"
Write-Output "Electron package Windows Installer"
Write-Output "   ---"
npm run build
If ($LastExitCode -gt 0){
    Throw "npm run build failed!"
}

Set-Location -Path "packages\wallet" -PassThru

Write-Output "   ---"
Write-Output "Increase the stack for silicoin command for (silicoin plots create) chiapos limitations"
# editbin.exe needs to be in the path
editbin.exe /STACK:8000000 daemon\silicoin.exe
Write-Output "   ---"

$packageVersion = "$env:SILICOIN_INSTALLER_VERSION"
$packageName = "Silicoin-$packageVersion"

Write-Output "packageName is $packageName"

Write-Output "   ---"
Write-Output "fix version in package.json"
choco install jq
cp package.json package.json.orig
jq --arg VER "$env:SILICOIN_INSTALLER_VERSION" '.version=$VER' package.json > temp.json
rm package.json
mv temp.json package.json
Write-Output "   ---"

Write-Output "   ---"
Write-Output "electron-packager"
electron-packager . Silicoin --asar.unpack="**\daemon\**" --overwrite --icon=.\src\assets\img\silicoin.ico --app-version=$packageVersion --executable-name=silicoin-blockchain
Write-Output "   ---"

Write-Output "   ---"
Write-Output "node winstaller.js"
node winstaller.js
Write-Output "   ---"

# Specific to pacr-dev branch, move these directories to where they used to be so the rest of the CI
# finds them where it expects to
Copy-Item "Silicoin-win32-x64" -Destination "..\..\" -Recurse
Copy-Item "release-builds" -Destination "..\..\" -Recurse

# Move back to the root of the gui directory
Set-Location -Path - -PassThru

git status

If ($env:HAS_SECRET) {
   Write-Output "   ---"
   Write-Output "Add timestamp and verify signature"
   Write-Output "   ---"
   signtool.exe timestamp /v /t http://timestamp.comodoca.com/ .\release-builds\windows-installer\SilicoinSetup-$packageVersion.exe
   signtool.exe verify /v /pa .\release-builds\windows-installer\SilicoinSetup-$packageVersion.exe
   }   Else    {
   Write-Output "Skipping timestamp and verify signatures - no authorization to install certificates"
}

git status

Write-Output "   ---"
Write-Output "Windows Installer complete"
Write-Output "   ---"

