import paho.mqtt.client as mqtt
import json
import csv
import os
from datetime import datetime

# --- KONFIGURASI BROKER & TOPIK ---
BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"

# --- KONFIGURASI CSV ---
CSV_FILENAME = "vms_telemetry_dataset.csv"

def init_csv():
    """Membuat file CSV dan Header untuk dataset mentah."""
    file_exists = os.path.isfile(CSV_FILENAME)
    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            # Header disesuaikan hanya untuk fitur input ML
            writer.writerow([
                "RSSI_dBm", "SNR_dB", "Distance_km", 
                "Radiation_Wm2", "Expected_Packets", "Received_Packets", 
                "Packet_Loss", "PDR_Percent"
            ])
            print(f"[INFO] File dataset {CSV_FILENAME} berhasil disiapkan.")

# --- EVENT HANDLERS ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[INFO] Berhasil terhubung ke HiveMQ Broker!")
        client.subscribe(TOPIC_TELEMETRY)
        print(f"[INFO] Mode Data Logging aktif di topik: {TOPIC_TELEMETRY}\n")
    else:
        print(f"[ERROR] Gagal terhubung, kode error: {rc}")

def on_message(client, userdata, msg):
    try:
        # 1. Ekstrak JSON dari ESP32 Pelabuhan
        payload_str = msg.payload.decode('utf-8')
        data = json.loads(payload_str)
        
        rssi = data.get("rssi", 0)
        snr = data.get("snr", 0)
        distance = data.get("distance_km", 0.0)
        radiation = data.get("radiation_wm2", 0.0)
        pdr = data.get("pdr_percent", 0.0)
        expected_packet = data.get("expected_packet", 0)
        received_packet = data.get("received_packet", 0)
        packet_loss = data.get("packet_loss", 0)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 2. Tampilkan di terminal secara ringkas
        print(f"[{timestamp}] DATA TEREKAM -> RSSI: {rssi} | SNR: {snr} | Jarak: {distance:.2f} | Rad: {radiation:.1f} | PDR: {pdr:.1f}%")
        
        # 3. Simpan baris data ke CSV
        with open(CSV_FILENAME, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                rssi, snr, distance, radiation, 
                expected_packet, received_packet, packet_loss, pdr
            ])
            
    except json.JSONDecodeError:
        print("[ERROR] Format data bukan JSON yang valid.")
    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan saat merekam: {e}")

# --- SETUP & RUN ---
if __name__ == "__main__":
    print("==================================================")
    print("     DATA LOGGER VMS (PENGUMPULAN DATASET ML)     ")
    print("==================================================")
    
    init_csv()
    
    client = mqtt.Client(client_id="VMS_Data_Logger_001")
    client.on_connect = on_connect
    client.on_message = on_message
    
    client.connect(BROKER, PORT, 60)
    
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Sesi logging dihentikan. File CSV siap diserahkan.")
        client.disconnect()