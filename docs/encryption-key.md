# Encryption key

Every Gree device has its own encryption key. The integration needs it to talk to the device.

In most cases you do not have to do anything. During setup the integration gets the key by itself, in one of two ways:

- **Locally.** It binds to the device with the generic Gree key. The device answers with its own key. This is the reverse engineered part of the Gree protocol.
- **From the cloud.** When you set up with a Gree account, the account holds the key of every bound device.

The key is stored in the config entry and is redacted in logs and diagnostics.

## When the local way fails

Some devices refuse the local bind after they were set up for remote access in the Gree app. The setup then fails with the message **Unable to bind the device**.

Try these in order.

1. **Set up with the cloud too.** Choose both discovery methods. The key comes from the account and control stays local. This is the simplest fix. See [connection-methods.md](connection-methods.md#mixed-setup).
2. **Get the key from the cloud yourself** and enter it in the **Encryption Key** field of the connection options. The [gree-api-client](https://github.com/luc10/gree-api-client) project explains how.
3. **Get the key from the Android app.** Pull the app database from an Android device, as described in [this Stack Overflow answer](https://stackoverflow.com/questions/9997976/android-pulling-sqlite-database-android-device):

   ```bash
   adb backup -f ~/backup.ab -noapk com.gree.ewpesmart
   dd if=data.ab bs=1 skip=24 | python -c "import zlib,sys;sys.stdout.write(zlib.decompress(sys.stdin.read()))" | tar -xvf -
   sqlite3 data.ab 'select privateKey from db_device_20170503;' # but table name can differ a little bit.
   ```

   If you get a UTF-8 error like `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xda in position 1: invalid continuation byte`, see [issue 318](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/318).

## The user ID

Some devices also check a user ID, called `uid`. The default is 0 and works for most devices. If your device ignores every command, the `uid` can be found in the same places as the key. Enter it in the **User ID** field of the connection options.

## Encryption versions

There are two versions of the encryption. The integration detects the version by itself when the **Encryption Version** option is **Auto-Detect**, which is the default. After a successful bind it stores the detected version. Set the version by hand only when you know the device needs it. Over the cloud the version is always 1.
