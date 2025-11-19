import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:local_auth/local_auth.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:pointycastle/export.dart' as pc;
import 'package:qr_code_scanner_plus/qr_code_scanner_plus.dart';

void main() => runApp(const MyApp());

const String userId = 'user-123';
const String baseUrl = "http://10.247.93.25:8889";

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: false,
          primarySwatch: Colors.teal,
          scaffoldBackgroundColor: const Color(0xFFEFEFEF),
        ),
        home: const Home(),
      );
}

class Home extends StatefulWidget {
  const Home({super.key});
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> {
  final storage = const FlutterSecureStorage();
  final auth = LocalAuthentication();
  static const MethodChannel _bleChannel = MethodChannel('ble_channel');

  String status = "Ready";
  bool isAdvertising = false;
  bool isLinked = false;

  // === Utility helpers ===
  String b64u(List<int> d) => base64Url.encode(d).replaceAll('=', '');
  Uint8List _b64UrlFlexDecode(String s) {
    final pad = (4 - (s.length % 4)) % 4;
    return base64Url.decode(s + ('=' * pad));
  }

  pc.SecureRandom _secureRandom() {
    final rnd = pc.FortunaRandom();
    final seed = Uint8List(32);
    final rs = math.Random.secure();
    for (int i = 0; i < seed.length; i++) seed[i] = rs.nextInt(256);
    rnd.seed(pc.KeyParameter(seed));
    return rnd;
  }

  Uint8List _sha256(List<int> message) =>
      pc.SHA256Digest().process(Uint8List.fromList(message));

  BigInt _bigIntFromBytes(Uint8List b) =>
      b.fold<BigInt>(BigInt.zero, (a, v) => (a << 8) | BigInt.from(v));

  Uint8List _toUnsignedBytes(BigInt v) {
    if (v == BigInt.zero) return Uint8List.fromList([0]);
    var hex = v.toRadixString(16);   // FIXED: correct method
    if (hex.length.isOdd) hex = '0$hex';
    return Uint8List.fromList([
      for (int i = 0; i < hex.length; i += 2)
        int.parse(hex.substring(i, i + 2), radix: 16)
    ]);
  }

  Uint8List _encodeDerLen(int len) {
    if (len < 0x80) return Uint8List.fromList([len]);
    final bytes = <int>[];
    for (var n = len; n > 0; n >>= 8) bytes.insert(0, n & 0xff);
    return Uint8List.fromList([0x80 | bytes.length, ...bytes]);
  }

  Uint8List _encodeDerRStoBytes(BigInt r, BigInt s) {
    Uint8List enc(BigInt v) {
      var b = _toUnsignedBytes(v);
      if (b.isNotEmpty && (b[0] & 0x80) != 0) b = Uint8List.fromList([0, ...b]);
      return b;
    }

    final rb = enc(r), sb = enc(s);
    final total = 2 + rb.length + 2 + sb.length;
    return Uint8List.fromList([
      0x30,
      ..._encodeDerLen(total),
      0x02,
      ..._encodeDerLen(rb.length),
      ...rb,
      0x02,
      ..._encodeDerLen(sb.length),
      ...sb
    ]);
  }

  Uint8List _ecdsaSignDerSha256P256(Uint8List msg, Uint8List dBytes) {
    final p = pc.ECDomainParameters('prime256v1');
    final priv = pc.ECPrivateKey(_bigIntFromBytes(dBytes), p);
    final s = pc.Signer('SHA-256/ECDSA')
      ..init(true,
          pc.ParametersWithRandom(pc.PrivateKeyParameter(priv), _secureRandom()));
    final sig = s.generateSignature(msg) as pc.ECSignature;
    final nHalf = p.n >> 1;
    final adjS = sig.s.compareTo(nHalf) > 0 ? p.n - sig.s : sig.s;
    return _encodeDerRStoBytes(sig.r, adjS);
  }

  Future<void> _ensureBlePermissions() async {
    final statuses = await [
      Permission.bluetoothAdvertise,
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.locationWhenInUse,
    ].request();
    if (statuses.values.any((s) => s.isDenied)) {
      throw Exception("BLE permissions not granted");
    }
  }

  Future<bool> _verifyProximity(String sid) async {
    await Future.delayed(const Duration(seconds: 2));
    return true;
  }

  // ===========================================================
  // 🔑 NEW: Auto-create key when Scan QR is tapped (no button)
  // ===========================================================
  Future<Uint8List> _ensureKey() async {
    var dBytes = await storage.read(key: 'passkey_priv_$userId');

    if (dBytes != null) {
      return _b64UrlFlexDecode(dBytes);
    }

    // Key does not exist → generate it now
    final rnd = math.Random.secure();
    final d = List<int>.generate(32, (_) => rnd.nextInt(256));
    await storage.write(
        key: 'passkey_priv_$userId', value: base64Url.encode(d));

    return Uint8List.fromList(d);
  }

  // ===========================================================
  // === Linking flow (unchanged, except auto key creation)
  // ===========================================================
  Future<void> scanAndLink() async {
    setState(() => status = "Preparing...");

    // 🔑 NEW: ensure private key exists
    final d = await _ensureKey();

    final qrData = await Navigator.push<String?>(
      context,
      MaterialPageRoute(builder: (_) => const ScanPage()),
    );
    if (qrData == null) return;

    final decoded = Uri.decodeFull(qrData.trim());
    final payload = jsonDecode(decoded);
    final sid = payload['sid'];
    final rpId = payload['rpId'];
    final urlFromQr = payload['url'];

    setState(() => status = "Initializing BLE + fetching challenge...");
    try {
      await _ensureBlePermissions();

      final res = await Future.wait([
        _bleChannel.invokeMethod('startBle', {"sid": sid}),
        http.get(Uri.parse('$baseUrl/pair?sid=$sid')),
      ]);

      isAdvertising = true;
      final http.Response resp = res[1] as http.Response;
      if (resp.statusCode != 200) {
        setState(() => status = "Pair fetch failed (${resp.statusCode})");
        return;
      }

      final j = jsonDecode(resp.body);
      final challengeB64 = j['challenge'];
      final sessionId = j['sessionId'];

      setState(() => status = "Checking proximity...");
      final nearby = await _verifyProximity(sid);
      if (!nearby) {
        await _stopBleAdvertising();
        setState(() => status = "Too far — move closer");
        return;
      }

      setState(() => status = "Waiting biometric...");
      final ok =
          await auth.authenticate(localizedReason: 'Confirm device linking');
      if (!ok) {
        await _stopBleAdvertising();
        setState(() => status = "Biometric cancelled");
        return;
      }

      final clientData = jsonEncode({
        "type": "webauthn.get",
        "challenge": challengeB64,
        "origin": urlFromQr,
        "crossOrigin": false
      });
      final clientBytes = utf8.encode(clientData);
      final rpHash = _sha256(utf8.encode(rpId));
      final clientHash = _sha256(clientBytes);
      final flags = <int>[0x05];
      final counter = <int>[0, 0, 0, 1];
      final authData = Uint8List.fromList([...rpHash, ...flags, ...counter]);
      final toSign = Uint8List.fromList([...rpHash, ...authData, ...clientHash]);

      final sig = _ecdsaSignDerSha256P256(toSign, d);

      final finish = await http.post(
        Uri.parse('$baseUrl/webauthn/finish'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          "sessionId": sessionId,
          "userId": userId,
          "credentialId": "demo-cred",
          "clientDataJSON": b64u(clientBytes),
          "authenticatorData": b64u(authData),
          "signature": b64u(sig),
        }),
      );

      await _stopBleAdvertising();
      if (finish.statusCode == 200) {
        setState(() {
          status = "Device linked successfully!";
          isLinked = true;
        });
      } else {
        setState(() => status = "Link failed: ${finish.body}");
      }
    } catch (e) {
      await _stopBleAdvertising();
      setState(() => status = "Error: $e");
    }
  }

  Future<void> _stopBleAdvertising() async {
    if (!isAdvertising) return;
    try {
      await _bleChannel.invokeMethod('stopBle');
    } catch (_) {}
    isAdvertising = false;
  }

  // ===========================================================
  // === UI (only one button now)
  // ===========================================================
  @override
  Widget build(BuildContext context) {
    final lower = status.toLowerCase();
    final isSuccess = lower.contains("success") || lower.contains("linked");
    final isError = lower.contains("error") || lower.contains("failed");

    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.teal,
        title: const Text(
          "Device Linking",
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
        ),
        centerTitle: true,
      ),
      body: Column(
        children: [
          const SizedBox(height: 24),

          // Status box
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: isError
                    ? Colors.red.shade100
                    : isSuccess
                        ? Colors.green.shade100
                        : Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                status,
                style: TextStyle(
                  fontSize: 16,
                  color: isError
                      ? Colors.red.shade700
                      : isSuccess
                          ? Colors.green.shade700
                          : Colors.black87,
                ),
              ),
            ),
          ),

          const SizedBox(height: 24),

          Expanded(
            child: Center(
              child: isSuccess
                  ? const Text(
                      "Device linked successfully!",
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                    )
                  : Text(
                      "Ready to link your device.\nTap Scan QR to begin.",
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 16, color: Colors.grey.shade700),
                    ),
            ),
          ),

          if (!isLinked)
            Padding(
              padding: const EdgeInsets.only(
                  left: 16, right: 16, bottom: 24, top: 8),
              child: Row(
                children: [
                  Expanded(
                    child: ElevatedButton(
                      onPressed: scanAndLink,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color.fromARGB(255, 4, 124, 44),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: const Text(
                        "Link a Device",
                        style: TextStyle(fontSize: 16),
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// === QR Scanner ===
class ScanPage extends StatefulWidget {
  const ScanPage({super.key});
  @override
  State<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<ScanPage> {
  final GlobalKey qrKey = GlobalKey(debugLabel: 'QR');
  QRViewController? controller;
  bool handled = false;

  void _onQRViewCreated(QRViewController c) {
    controller = c;
    c.scannedDataStream.listen((scanData) async {
      if (handled) return;
      handled = true;
      await Future.delayed(const Duration(milliseconds: 300));
      controller?.pauseCamera();
      Navigator.pop(context, scanData.code);
    });
  }

  @override
  void dispose() {
    controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          backgroundColor: Colors.teal,
          title: const Text("Scan QR"),
        ),
        body: Stack(
          children: [
            QRView(
              key: qrKey,
              onQRViewCreated: _onQRViewCreated,
              overlay: QrScannerOverlayShape(
                borderColor: Colors.teal,
                borderRadius: 10,
                borderLength: 30,
                borderWidth: 8,
                cutOutSize: 250,
              ),
            ),
            const Positioned(
              bottom: 40,
              left: 0,
              right: 0,
              child: Text(
                "Align the QR code within the frame",
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w500),
              ),
            ),
          ],
        ),
      );
}
