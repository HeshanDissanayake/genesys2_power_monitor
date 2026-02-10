import sys
import time
import csv
import smbus2
import struct

# INA219 addresses on Genesys2
INA219_ADDRESSES = [0x40, 0x41, 0x44, 0x45, 0x48, 0x4c]
bus = smbus2.SMBus(1)

SAMPLE_INTERVAL = 0.001  # 1 ms
LOG_INTERVAL = 0.001       # 0.1 second

def read_ina219(address):
    try:
        # Bus voltage
        raw = bus.read_word_data(address, 0x02)
        raw = struct.unpack("<H", struct.pack(">H", raw))[0]
        voltage = (raw >> 3) * 4e-3

        # Current (signed)
        raw = bus.read_word_data(address, 0x04)
        raw = struct.unpack("<h", struct.pack(">H", raw))[0]
        current = raw * 1e-3

        # Power (W)
        return voltage * current
    except Exception:
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 monitor_log.py <log_filename>")
        sys.exit(1)

    log_file = sys.argv[1]
    print(f"Logging ENERGY per device to {log_file} ...")

    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)

        # CSV header: timestamp + one column per INA219
        header = ["Time"] + [f"Device_{hex(addr)}_Energy(J)" for addr in INA219_ADDRESSES]
        writer.writerow(header)

        # Initialize energy accumulators
        energy_acc = {addr: 0.0 for addr in INA219_ADDRESSES}
        last_log_time = time.time()

        try:
            while True:
                t_start = time.time()

                # Sample all devices
                for addr in INA219_ADDRESSES:
                    p = read_ina219(addr)
                    if p is not None:
                        energy_acc[addr] += p * SAMPLE_INTERVAL

                # Check if it's time to log
                if t_start - last_log_time >= LOG_INTERVAL:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    row = [timestamp] + [f"{energy_acc[addr]:.6f}" for addr in INA219_ADDRESSES]
                    writer.writerow(row)
                    f.flush()
                    last_log_time = t_start

                # Sleep to maintain 1 ms sampling
                elapsed = time.time() - t_start
                if elapsed < SAMPLE_INTERVAL:
                    time.sleep(SAMPLE_INTERVAL - elapsed)

        except KeyboardInterrupt:
            print("\nLogging stopped.")

if __name__ == "__main__":
    main()
