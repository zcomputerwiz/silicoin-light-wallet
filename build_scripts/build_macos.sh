#!/bin/bash

set -euo pipefail

pip install setuptools_scm
# The environment variable SILICOIN_INSTALLER_VERSION needs to be defined.
# If the env variable NOTARIZE and the username and password variables are
# set, this will attempt to Notarize the signed DMG.
SILICOIN_INSTALLER_VERSION=$(python installer-version.py)

if [ ! "$SILICOIN_INSTALLER_VERSION" ]; then
	echo "WARNING: No environment variable SILICOIN_INSTALLER_VERSION set. Using 0.0.0."
	SILICOIN_INSTALLER_VERSION="0.0.0"
fi
echo "Silicoin Installer Version is: $SILICOIN_INSTALLER_VERSION"

echo "Installing npm and electron packagers"
npm install electron-installer-dmg -g
# Pinning electron-packager and electron-osx-sign to known working versions
# Current packager uses an old version of osx-sign, so if we install the newer sign package
# things break
npm install electron-packager@15.4.0 -g
npm install electron-osx-sign@v0.5.0 -g
npm install notarize-cli -g
npm install lerna -g

echo "Create dist/"
sudo rm -rf dist
mkdir dist

echo "Create executables with pyinstaller"
pip install pyinstaller==4.5

echo "Create executables with pyinstaller"
SPEC_FILE=$(python -c 'import silicoin; print(silicoin.PYINSTALLER_SPEC_PATH)')
pyinstaller --log-level=INFO "$SPEC_FILE"
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "pyinstaller failed!"
	exit $LAST_EXIT_CODE
fi
cp -r dist/daemon ../silicoin-light-gui/packages/wallet
cd .. || exit
cd silicoin-light-gui || exit

echo "npm build"
npm install
npm run build

LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "npm run build failed!"
	exit $LAST_EXIT_CODE
fi

# sets the version for silicoin-blockchain in package.json
brew install jq
cd ./packages/wallet
cp package.json package.json.orig
jq --arg VER "$SILICOIN_INSTALLER_VERSION" '.version=$VER' package.json > temp.json && mv temp.json package.json

electron-packager . Silicoin --asar.unpack="**/daemon/**" --platform=darwin \
--icon=src/assets/img/Silicoin.icns --overwrite --app-bundle-id=net.silicoin.blockchain \
--appVersion=$SILICOIN_INSTALLER_VERSION
LAST_EXIT_CODE=$?

# reset the package.json to the original
mv package.json.orig package.json

if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-packager failed!"
	exit $LAST_EXIT_CODE
fi

if [ "$NOTARIZE" == true ]; then
  electron-osx-sign Silicoin-darwin-x64/Silicoin.app --platform=darwin \
  --hardened-runtime=true --provisioning-profile=silicoinblockchain.provisionprofile \
  --entitlements=entitlements.mac.plist --entitlements-inherit=entitlements.mac.plist \
  --no-gatekeeper-assess
fi
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-osx-sign failed!"
	exit $LAST_EXIT_CODE
fi

mv Silicoin-darwin-x64 ../../../build_scripts/dist/
cd ../../../build_scripts || exit

DMG_NAME="Silicoin-$SILICOIN_INSTALLER_VERSION.dmg"
echo "Create $DMG_NAME"
mkdir final_installer
electron-installer-dmg dist/Silicoin-darwin-x64/Silicoin.app Silicoin-$SILICOIN_INSTALLER_VERSION \
--overwrite --out final_installer
LAST_EXIT_CODE=$?
if [ "$LAST_EXIT_CODE" -ne 0 ]; then
	echo >&2 "electron-installer-dmg failed!"
	exit $LAST_EXIT_CODE
fi

if [ "$NOTARIZE" == true ]; then
	echo "Notarize $DMG_NAME on ci"
	cd final_installer || exit
  notarize-cli --file=$DMG_NAME --bundle-id net.silicoin.blockchain \
	--username "$APPLE_NOTARIZE_USERNAME" --password "$APPLE_NOTARIZE_PASSWORD"
  echo "Notarization step complete"
else
	echo "Not on ci or no secrets so skipping Notarize"
fi

# Notes on how to manually notarize
#
# Ask for username and password. password should be an app specific password.
# Generate app specific password https://support.apple.com/en-us/HT204397
# xcrun altool --notarize-app -f Silicoin-0.1.X.dmg --primary-bundle-id net.silicoin.blockchain -u username -p password
# xcrun altool --notarize-app; -should return REQUEST-ID, use it in next command
#
# Wait until following command return a success message".
# watch -n 20 'xcrun altool --notarization-info  {REQUEST-ID} -u username -p password'.
# It can take a while, run it every few minutes.
#
# Once that is successful, execute the following command":
# xcrun stapler staple Silicoin-0.1.X.dmg
#
# Validate DMG:
# xcrun stapler validate Silicoin-0.1.X.dmg
