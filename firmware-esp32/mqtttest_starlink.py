import paho.mqtt.client as mqtt
import json
import uuid

# Konfigurasi EMQX Broker (Sesuai dengan di ESP32)
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC = "vms_hybrid_2026/starlink_telemetry"


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("[*] Terhubung ke Broker EMQX!")
        print(f"[*] Menunggu telemetri dari kapal di topik: {MQTT_TOPIC}...\n")
        # Mulai mendengarkan topik (subscribe)
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"[!] Gagal terhubung ke Broker. Kode Error: {reason_code}")
# Callback saat pesan baru masuk
def on_message(client, userdata, msg):
    try:
        # Decode pesan dari bentuk byte ke string, lalu ubah ke Dictionary (JSON)
        payload_str = msg.payload.decode('utf-8')
        data = json.loads(payload_str)
        
        print("=== TELEMETRI STARLINK MASUK ===")
        
        # Mengecek apakah GPS Fix atau Loss
        if "gps_status" in data and data["gps_status"] == "NO_FIX":
            print(f"[!] Status GPS : HILANG / NO FIX")
        else:
            print(f"Latitude     : {data.get('latitude')}")
            print(f"Longitude    : {data.get('longitude')}")
            
        print(f"Radiasi Matahari : {data.get('radiation')} W/m2")
        print("================================\n")
        
    except json.JSONDecodeError:
        print(f"[!] Error: Pesan yang masuk bukan format JSON yang valid -> {msg.payload}")

random_client_id = f"vms-dashboard-python-{uuid.uuid4().hex[:8]}"
print(f"[*] Menggunakan Client ID: {random_client_id}")

# 2. Masukkan Client ID ke inisialisasi MQTT
# (Catatan: paho-mqtt versi 2.x mensyaratkan CallbackAPIVersion)
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=random_client_id)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()
try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[*] Program dihentikan.")
    client.disconnect()