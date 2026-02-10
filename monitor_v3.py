import time
import os
import csv
import datetime
import smbus2

# Import the INA219 library
# Assuming the library is in a subdirectory 'pi_ina219' with an __init__.py or just as a module
# Adjust sys.path or structure as needed. For now we assume ina219.py is available.
# Since the user context showed `pi_ina219/ina219.py`, we might need to append path.
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'pi_ina219'))

try:
    from ina219 import INA219
except ImportError:
    print("Error: Could not import 'ina219'. Ensure 'pi_ina219' directory is present.")
    sys.exit(1)

# ==========================================
# USER CONFIGURATION
# ==========================================
# Hardware Config
SHUNT_OHMS = 0.005
MAX_EXPECTED_AMPS = 0.2
I2C_BUS_NUMBER = 1
INA219_ADDRESSES = [0x40, 0x41, 0x44, 0x45, 0x48, 0x4c]

# Logging Config
LOG_DIR = "logs"
LOG_READ_BUS_VOLTAGE = False
LOG_READ_SHUNT_VOLTAGE = False
LOG_READ_CURRENT = True
LOG_READ_POWER = True

# INA219 Configuration (using library constants)
# Range: RANGE_16V, RANGE_32V
CFG_RANGE = INA219.RANGE_16V

# Gain: GAIN_1_40MV, GAIN_2_80MV, ... GAIN_AUTO
CFG_GAIN = INA219.GAIN_1_40MV

# ADC Config: ADC_12BIT (default), ADC_128SAMP, etc.
CFG_ADC = INA219.ADC_12BIT


if __name__ == "__main__":
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)

        print(f"Initializing {len(INA219_ADDRESSES)} sensors...")
        sensors = []

        # Initialize sensors using the library
        for addr in INA219_ADDRESSES:
            print(f"-- Configuring Sensor at 0x{addr:02x} --")
            sensor = INA219(address=addr, shunt_ohms=SHUNT_OHMS, max_expected_amps=MAX_EXPECTED_AMPS, busnum=I2C_BUS_NUMBER)
            # Store address on the object manually since the library doesn't expose it
            sensor.address = addr
            
            # Use strict manual config as per user request history
            sensor.configure(voltage_range=CFG_RANGE, gain=CFG_GAIN, bus_adc=CFG_ADC, shunt_adc=CFG_ADC)
            sensors.append(sensor)

        print("\nStarting Fast Monitoring... (Press Ctrl+C to stop)")
        print("Buffering data to RAM for maximum speed...")
        time.sleep(1)

        # Prepare for Fast Loop
        # The library abstracts reading, but for maximum speed we still want to be careful.
        # Calling sensor.voltage() does a bus read + math.
        # Calling sensor.current() does a bus read + math.
        # To match the "fast mode" of v2, we should just capture data.
        # BUT: The user asked to use the lib to "read the sensor values and converts".
        # Doing conversion inside the fast loop slows it down.
        # However, the user specifically asked to use the LIB. The lib does conversion on read.
        # If speed is critical, we should read raw registers then use lib for config.
        # But if we want to "use the lib to read", we must accept some CPU overhead.
        
        # We will use the library's read methods inside the loop.
        # Optimized list of (sensor_obj, read_functions)
        
        fast_ops = []
        for s in sensors:
            ops = []
            if LOG_READ_SHUNT_VOLTAGE: ops.append(('shunt', s.shunt_voltage))
            if LOG_READ_BUS_VOLTAGE:   ops.append(('bus', s.voltage)) # Volts
            if LOG_READ_POWER:         ops.append(('power', s.power))     # mW
            if LOG_READ_CURRENT:       ops.append(('current', s.current))   # mA
            fast_ops.append((s.address, ops))

        ram_buffer = [] # format: (timestamp, address, {key: value})

        try:
            while True:
                # Capture Loop
                t = time.time()
                for addr, ops in fast_ops:
                    vals = {}
                    try:
                        for key, func in ops:
                            # Library reads return float values immediately
                            vals[key] = func()
                        ram_buffer.append((t, addr, vals))
                    except Exception:
                        pass # Skip I2C errors to keep flow

        except KeyboardInterrupt:
            print(f"\nCapture stopped. Processing {len(ram_buffer)} samples...")
            
            # Prepare CSV Writers
            f_names = {}
            if LOG_READ_BUS_VOLTAGE: f_names['bus'] = f"{LOG_DIR}/log_bus_voltage.csv"
            if LOG_READ_CURRENT:     f_names['current'] = f"{LOG_DIR}/log_current.csv"
            if LOG_READ_POWER:       f_names['power'] = f"{LOG_DIR}/log_power.csv"
            if LOG_READ_SHUNT_VOLTAGE: f_names['shunt'] = f"{LOG_DIR}/log_shunt_voltage.csv"

            files = {}
            writers = {}
            
            try:
                for key, fname in f_names.items():
                    f = open(fname, 'w', newline='')
                    files[key] = f
                    writers[key] = csv.writer(f)
                    
                    # Header
                    headers = ["Timestamp"] + [f"0x{addr:02x}" for addr in INA219_ADDRESSES]
                    writers[key].writerow(headers)

                print("Writing to CSV...")
                
                # Regroup data by sweep (Time based)
                current_t = -1
                row_data = {} # addr -> dict of values
                
                def commit_row(timestamp, data):
                    if not data: return
                    ts_str = datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                    
                    # Prepare rows
                    rows = {k: [ts_str] for k in writers.keys()}
                    
                    for addr in INA219_ADDRESSES:
                        if addr in data:
                            for k in writers.keys():
                                # Values are already floats/converted
                                val = data[addr].get(k, "")
                                if val != "":
                                    rows[k].append(f"{val:.4f}")
                                else:
                                    rows[k].append("")
                        else:
                            for k in writers.keys():
                                rows[k].append("")

                    for k, w in writers.items():
                        w.writerow(rows[k])

                for t, addr, vals in ram_buffer:
                    # New sweep detection
                    if addr in row_data:
                        commit_row(current_t, row_data)
                        row_data = {}
                        current_t = t
                    
                    if current_t == -1:
                        current_t = t
                    
                    row_data[addr] = vals
                
                commit_row(current_t, row_data)
                print("Done.")

            finally:
                for f in files.values():
                    f.close()

    except Exception as e:
        print(f"Error: {e}")
