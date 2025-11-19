package com.example.passkey_mobile_app

import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.os.ParcelUuid
import android.util.Log
import androidx.annotation.NonNull
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.security.MessageDigest

class MainActivity : FlutterFragmentActivity() {

    private val CHANNEL = "ble_channel"
    private var advertiser: BluetoothLeAdvertiser? = null
    private val TAG = "PAL-BLE"
    private val SERVICE_UUID =
        ParcelUuid.fromString("b28a0001-2d9a-4a1f-9ad7-1234567890ab")

    override fun configureFlutterEngine(@NonNull flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        Log.i(TAG, "configureFlutterEngine — setting up BLE MethodChannel")

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "startBle" -> {
                        val sid = call.argument<String>("sid")
                        if (sid != null) {
                            Log.i(TAG, "startBle() called from Dart with sid=$sid")
                            startAdvertising(sid)
                            result.success("started")
                        } else {
                            result.error("ERR", "Missing SID", null)
                        }
                    }

                    "stopBle" -> {
                        Log.i(TAG, "stopBle() called from Dart")
                        stopAdvertising()
                        result.success("stopped")
                    }

                    else -> result.notImplemented()
                }
            }
    }

    private fun startAdvertising(sid: String) {
    try {
        val adapter = BluetoothAdapter.getDefaultAdapter()
        advertiser = adapter.bluetoothLeAdvertiser
        if (advertiser == null) {
            Log.e(TAG, "❌ No BluetoothLeAdvertiser available (device unsupported)")
            return
        }

        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
            .setConnectable(false)
            .build()

        // 👉 Send SID as plain ASCII (12 bytes)
        val payload = sid.toByteArray(Charsets.US_ASCII)
        Log.i(TAG, "Advertising plain SID='$sid' (len=${payload.size})")

        val data = AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            // ❌ REMOVE this line to stay under 31-byte limit
            // .addServiceUuid(SERVICE_UUID)
            // ✅ Only manufacturer data with small payload
            .addManufacturerData(0x1234, payload)
            .build()

        advertiser?.startAdvertising(settings, data, advertiseCallback)
        Log.i(TAG, "✅ BLE advertising requested")

        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException — check Bluetooth permissions: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "startAdvertising() failed: ${e.message}")
        }
    }



    private fun stopAdvertising() {
        try {
            advertiser?.stopAdvertising(advertiseCallback)
            Log.i(TAG, "Advertising stopped cleanly")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping advertising: ${e.message}")
        }
    }

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
            Log.i(TAG, "✅ BLE advertising successfully started")
        }

        override fun onStartFailure(errorCode: Int) {
            val reason = when (errorCode) {
                ADVERTISE_FAILED_DATA_TOO_LARGE -> "DATA_TOO_LARGE"
                ADVERTISE_FAILED_TOO_MANY_ADVERTISERS -> "TOO_MANY_ADVERTISERS"
                ADVERTISE_FAILED_ALREADY_STARTED -> "ALREADY_STARTED"
                ADVERTISE_FAILED_INTERNAL_ERROR -> "INTERNAL_ERROR"
                ADVERTISE_FAILED_FEATURE_UNSUPPORTED -> "FEATURE_UNSUPPORTED"
                else -> "UNKNOWN"
            }
            Log.e(TAG, "❌ BLE advertising failed: $reason (errorCode=$errorCode)")
        }
    }
}
