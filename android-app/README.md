# RidePy Android

Native Android WebView wrapper for the deployed RidePy Flask application.

## Requirements

- Android Studio 2026.1.2 or compatible
- JDK 17 (bundled with Android Studio)
- Android SDK Platform 36 and Build Tools 36.0.0
- Internet access during the first Gradle sync

## Build a debug APK

1. Open the `android-app` folder in Android Studio.
2. Allow Gradle sync and install the requested Android SDK packages.
3. Select **Build > Build APK(s)**.
4. Find the APK under `app/build/outputs/apk/debug/app-debug.apk`.

The debug APK is suitable for direct testing on Android 8.0 (API 26) or later.
For Play Store or public distribution, create and safely retain a release signing key, then build a signed APK or Android App Bundle.

## Production website

The app loads:

`https://vehiclerentalandreservationsystem.vercel.app/login`

Change `APP_URL` and `APP_HOST` together in `MainActivity.java` if the production domain changes.
