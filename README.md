# LoRa Probabilistic Switching

Project ini berisi simulasi dan monitoring sistem komunikasi maritim hybrid LoRa-Starlink berbasis probabilistic switching.

Sistem menggunakan parameter RSSI, SNR, dan jarak untuk menghitung PLoRa sebagai dasar pemilihan jalur komunikasi antara LoRa dan Starlink.

## Fitur Utama

- Simulasi probabilistic switching LoRa-Starlink
- Perhitungan PLoRa berbasis RSSI, SNR, dan jarak
- Monitoring data telemetry via MQTT
- Logging data ke CSV
- Visualisasi grafik hasil simulasi dan monitoring
- Struktur folder siap dikembangkan untuk dashboard web dan firmware ESP32

## Struktur Folder

    data/        Dataset raw, processed, dan sample
    docs/        Dokumentasi, flowchart, dan laporan
    results/     Grafik dan tabel hasil pengujian
    scripts/     Script utama untuk menjalankan program
    src/         Source code modular project
    firmware/    Tempat kode ESP32
    hardware/    Tempat schematic, PCB, enclosure, dan BOM

## Instalasi

Clone repository:

    git clone https://github.com/Akhul027/lora-prob-switching.git
    cd lora-prob-switching

Buat virtual environment:

    python3 -m venv venv
    source venv/bin/activate

Install dependency:

    pip install -r requirements.txt

## Menjalankan Simulasi

    python scripts/run_simulation.py

## Menjalankan Live Monitoring MQTT

    python scripts/run_live_monitoring.py

## Output Data

Output telemetry disimpan di:

    data/raw/

Output simulasi disimpan di:

    data/processed/
    results/figures/

## Catatan

Folder venv, cache Python, file video besar, dan file sementara tidak dimasukkan ke GitHub.
