"""
vms_switcher.py
================================================================
Single-file Python untuk VMS Probabilistic Switching.

VERSI REVISI: 
Telah disesuaikan dengan payload JSON aktual dari ESP32 (Node B).
- Jarak (distance_km) dan PDR langsung diambil dari ESP32.
- Publikasi perintah (decision) menggunakan plain text (bukan JSON).
================================================================
"""

import csv
import json
import os
import time
import uuid
from datetime import datetime
from enum import Enum

import paho.mqtt.client as mqtt


# ================================================================
# KONFIGURASI
# ================================================================

MQTT_BROKER = "broker.emqx.io"  # Ubah baris ini
MQTT_PORT = 1883                # Port tetap 1883 untuk koneksi standar
TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"
TOPIC_DECISION = "vms_hybrid_2026/switching_decision"
MQTT_QOS = 1

# --- Flag perilaku ---
# True: Python jadi otak (publish keputusan ke ESP32)
# False: Python cuma observer (hanya catat CSV, tidak interferensi rekan tim)
PUBLISH_DECISION = True

# --- Bobot model probabilistik (Subbab 3.8) ---
OMEGA_RSSI = 0.5
OMEGA_SNR = 0.3
OMEGA_DISTANCE = 0.2

# --- Rentang normalisasi ---
RSSI_MIN, RSSI_MAX = -120.0, -30.0      # dBm (batas reliability praktis)
SNR_MIN, SNR_MAX = -20.0, 10.0          # dB
DISTANCE_MIN, DISTANCE_MAX = 0.0, 15.0  # km

# --- Ambang batas probabilitas (Subbab 3.9) ---
P_HIGH = 0.65
P_SAFE = 0.55
P_LOW = 0.35

# --- Timing ---
MIN_STATE_DURATION_SEC = 5.0
STARLINK_BOOT_TIME_SEC = 45.0

# --- CSV ---
CSV_FILENAME = "vms_telemetry_dataset.csv"
CSV_HEADER = [
    "RSSI_dBm", "SNR_dB", "Distance_km",
    "Radiation_Wm2", "Expected_Packets", "Received_Packets",
    "Packet_Loss", "PDR_Percent",
    "P_LoRa", "State", "Target_Link", "Timestamp",
]


# ================================================================
# VALIDASI KONFIGURASI
# ================================================================
assert abs((OMEGA_RSSI + OMEGA_SNR + OMEGA_DISTANCE) - 1.0) < 1e-6, \
    "Bobot omega harus berjumlah 1.0"
assert P_LOW < P_SAFE < P_HIGH, \
    f"Urutan ambang salah: P_LOW({P_LOW}) < P_SAFE({P_SAFE}) < P_HIGH({P_HIGH})"


# ================================================================
# STATE ENUM
# ================================================================
class SystemState(Enum):
    LORA_ACTIVE = "LORA"
    SWITCHING = "SWITCHING"
    STARLINK_ACTIVE = "STARLINK"


# ================================================================
# FUNGSI MATEMATIS
# ================================================================

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalize(value: float, vmin: float, vmax: float) -> float:
    if vmax <= vmin:
        return 0.0
    return clamp01((value - vmin) / (vmax - vmin))


def compute_p_lora(rssi: float, snr: float, distance_km: float) -> dict:
    """P_LoRa = w1*RSSI_norm + w2*SNR_norm + w3*D_norm."""
    rssi_norm = normalize(rssi, RSSI_MIN, RSSI_MAX)
    snr_norm = normalize(snr, SNR_MIN, SNR_MAX)
    distance_norm = 1.0 - normalize(distance_km, DISTANCE_MIN, DISTANCE_MAX)
    
    p = (OMEGA_RSSI * rssi_norm +
         OMEGA_SNR * snr_norm +
         OMEGA_DISTANCE * distance_norm)
         
    return {
        "p_lora": p,
        "rssi_norm": rssi_norm,
        "snr_norm": snr_norm,
        "distance_norm": distance_norm,
    }


# ================================================================
# STATE MACHINE
# ================================================================

class Switcher:
    def __init__(self):
        self.state = SystemState.LORA_ACTIVE
        self.state_entered_at = time.time()
        self.switching_started_at = None
        self.switch_count = 0
    
    def _time_in_state(self) -> float:
        return time.time() - self.state_entered_at
    
    def _transition_to(self, new_state: SystemState, reason: str):
        if new_state == self.state:
            return
        print(f"  [STATE] {self.state.value} -> {new_state.value} | {reason}")
        self.state = new_state
        self.state_entered_at = time.time()
        self.switch_count += 1
        if new_state == SystemState.SWITCHING:
            self.switching_started_at = time.time()
    
    def update(self, rssi: float, snr: float, distance_km: float) -> dict:
        comp = compute_p_lora(rssi, snr, distance_km)
        p_lora = comp["p_lora"]
        
        min_pass = self._time_in_state() >= MIN_STATE_DURATION_SEC
        reason = f"P_LoRa={p_lora:.3f}"
        
        if self.state == SystemState.LORA_ACTIVE:
            if p_lora < P_LOW and min_pass:
                self._transition_to(SystemState.SWITCHING,
                                    f"P={p_lora:.3f} < P_LOW={P_LOW}")
                reason = "Degradasi LoRa - booting Starlink"
        
        elif self.state == SystemState.SWITCHING:
            boot_elapsed = time.time() - self.switching_started_at
            if p_lora >= P_SAFE and min_pass:
                self._transition_to(SystemState.LORA_ACTIVE,
                                    f"LoRa pulih (P={p_lora:.3f})")
                reason = "Switching dibatalkan"
            elif boot_elapsed >= STARLINK_BOOT_TIME_SEC:
                self._transition_to(SystemState.STARLINK_ACTIVE,
                                    f"Starlink ready ({boot_elapsed:.1f}s)")
                reason = "Starlink siap"
            else:
                reason = f"Tunggu boot ({boot_elapsed:.0f}/{STARLINK_BOOT_TIME_SEC:.0f}s)"
        
        elif self.state == SystemState.STARLINK_ACTIVE:
            if p_lora >= P_SAFE and min_pass:
                self._transition_to(SystemState.LORA_ACTIVE,
                                    f"P={p_lora:.3f} >= P_SAFE={P_SAFE}")
                reason = "LoRa pulih"
        
        target = "STARLINK" if self.state == SystemState.STARLINK_ACTIVE else "LORA"
        
        return {
            "state": self.state.value,
            "target_link": target,
            "p_lora": round(p_lora, 4),
            "rssi_norm": round(comp["rssi_norm"], 4),
            "snr_norm": round(comp["snr_norm"], 4),
            "distance_norm": round(comp["distance_norm"], 4),
            "distance_km": round(distance_km, 3),
            "reason": reason,
            "timestamp": time.time(),
        }


# ================================================================
# CSV LOGGER
# ================================================================

class CsvLogger:
    def __init__(self, filename: str):
        self.filename = filename
        self._init_file()
    
    def _init_file(self):
        file_exists = os.path.isfile(self.filename)
        self.file = open(self.filename, mode="a", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        if not file_exists:
            self.writer.writerow(CSV_HEADER)
            self.file.flush()
            print(f"[CSV] File baru: {self.filename}")
        else:
            print(f"[CSV] Append ke file existing: {self.filename}")
    
    def log(self, telemetry: dict, decision: dict, pdr: dict):
        row = [
            telemetry.get("rssi", 0.0),
            telemetry.get("snr", 0.0),
            decision["distance_km"],
            telemetry.get("radiation_wm2", 0.0), # Sesuai JSON ESP32
            pdr["expected"],
            pdr["received"],
            pdr["packet_loss"],
            pdr["pdr_percent"],
            decision["p_lora"],
            decision["state"],
            decision["target_link"],
            datetime.fromtimestamp(decision["timestamp"]).isoformat(),
        ]
        self.writer.writerow(row)
        self.file.flush()
    
    def close(self):
        if self.file:
            self.file.close()


# ================================================================
# BRIDGE UTAMA
# ================================================================

class VmsBridge:
    def __init__(self):
        self.switcher = Switcher()
        self.csv = CsvLogger(CSV_FILENAME)
        self.packet_count = 0
        
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"vms_python_{uuid.uuid4().hex[:8]}", # Menggunakan UUID acak 8 karakter
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[MQTT] Connected to {MQTT_BROKER}:{MQTT_PORT}")
            client.subscribe(TOPIC_TELEMETRY, qos=MQTT_QOS)
            print(f"[MQTT] Subscribed: {TOPIC_TELEMETRY}")
            if PUBLISH_DECISION:
                print(f"[MQTT] Akan publish ke: {TOPIC_DECISION}")
            else:
                print(f"[MQTT] Mode OBSERVER - tidak publish decision")
            print()
        else:
            print(f"[MQTT] Connection failed: {reason_code}")
    
    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        print(f"[MQTT] Disconnected (rc={reason_code}), auto-reconnect...")
    
    def _on_message(self, client, userdata, msg):
        try:
            telemetry = json.loads(msg.payload.decode())
            
            # Validasi input sesuai dengan JSON dari ESP32
            required = ["rssi", "snr", "distance_km", "radiation_wm2"]
            missing = [f for f in required if f not in telemetry]
            if missing:
                print(f"[WARN] Telemetri tanpa field: {missing}")
                return
            
            self.packet_count += 1
            
            # Tarik data PDR yang sudah dihitung oleh ESP32
            pdr_stats = {
                "expected": telemetry.get("expected_packet", 0),
                "received": telemetry.get("received_packet", 0),
                "packet_loss": telemetry.get("packet_loss", 0),
                "pdr_percent": telemetry.get("pdr_percent", 0.0),
            }
            
            # Evaluasi model
            decision = self.switcher.update(
                rssi=float(telemetry["rssi"]),
                snr=float(telemetry["snr"]),
                distance_km=float(telemetry["distance_km"])
            )
            
            # Logging ke CSV
            self.csv.log(telemetry, decision, pdr_stats)
            
            # Tembak perintah ke Node B jika sedang mode otak
            if PUBLISH_DECISION:
                self._publish_decision(decision)
            
            # Cetak ke terminal
            self._print_log(telemetry, decision, pdr_stats)
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parse: {e} | payload: {msg.payload[:80]}")
        except (KeyError, ValueError) as e:
            print(f"[ERROR] Telemetri invalid: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected: {e}")
    
    def _publish_decision(self, decision: dict):
        # Format diubah ke plain text sesuai dengan strncmp di ESP32
        command_string = decision["target_link"]
        self.client.publish(
            TOPIC_DECISION,
            command_string,
            qos=MQTT_QOS,
        )
    
    def _print_log(self, telemetry: dict, decision: dict, pdr: dict):
        rad = telemetry.get("radiation_wm2", 0)
        print(
            f"[#{self.packet_count:04d}] "
            f"RSSI={telemetry['rssi']:6.1f} "
            f"SNR={telemetry['snr']:5.1f} "
            f"d={decision['distance_km']:5.2f}km "
            f"Rad={rad:5.0f} "
            f"PDR={pdr['pdr_percent']:5.1f}% "
            f"P={decision['p_lora']:.3f} "
            f"[{decision['state']:10s}] -> {decision['target_link']}"
        )
    
    def run(self):
        print("=" * 70)
        print("  VMS PROBABILISTIC SWITCHING — Python Bridge (REVISI)")
        print("=" * 70)
        print(f"Broker        : {MQTT_BROKER}:{MQTT_PORT}")
        print(f"Bobot         : omega = ({OMEGA_RSSI}, {OMEGA_SNR}, {OMEGA_DISTANCE})")
        print(f"Ambang        : P_HIGH={P_HIGH}, P_SAFE={P_SAFE}, P_LOW={P_LOW}")
        print(f"Mode          : {'PUBLISHER (otak)' if PUBLISH_DECISION else 'OBSERVER (catat saja)'}")
        print(f"CSV output    : {CSV_FILENAME}")
        print("=" * 70)
        
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        except Exception as e:
            print(f"[FATAL] Gagal connect: {e}")
            return
        
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n[MAIN] Stopped by user.")
        finally:
            self._cleanup()
    
    def _cleanup(self):
        print("\n" + "=" * 70)
        print("  RINGKASAN SESI")
        print("=" * 70)
        print(f"Total paket diterima : {self.packet_count}")
        print(f"Total switch events  : {self.switcher.switch_count}")
        print(f"State akhir          : {self.switcher.state.value}")
        print(f"CSV tersimpan        : {CSV_FILENAME}")
        print("=" * 70)
        self.csv.close()
        self.client.disconnect()


# ================================================================
# MAIN
# ================================================================
if __name__ == "__main__":
    bridge = VmsBridge()
    bridge.run()