import smbus2
import struct
import time
import os
import csv
import datetime

# ==========================================
# USER CONFIGURATION & CALIBRATION
# ==========================================
# Change these values to match your hardware setup
SHUNT_OHMS = 0.005      # The value of the shunt resistor in Ohms (e.g., 0.1, 0.01)
MAX_EXPECTED_AMPS = 3 # Maximum current expected in Amps
# Logging Configuration
LOGGING_ENABLED = True
LOG_DIR = "logs"
# Select which data to read and log (Set to False to improve sampling rate)
LOG_READ_BUS_VOLTAGE = False
LOG_READ_SHUNT_VOLTAGE = False
LOG_READ_CURRENT = True
LOG_READ_POWER = False
# I2C Address of the sensor
INA219_ADDRESSES = [0x40, 0x41, 0x44, 0x45, 0x48, 0x4c]
I2C_BUS_NUMBER = 1

# ==========================================
# INA219 CONFIGURATION PARAMETERS
# ==========================================
# Bus Voltage Range (16 or 32 V)
CFG_BUS_RANGE_V = 16 

# Gain / Shunt Voltage Range (40, 80, 160, or 320 mV)
CFG_GAIN_MV = 40

# ADC Averaging Samples (1, 2, 4, 8, 16, 32, 64, 128)
# Higher averaging = cleaner signal but slower update rate.
# 1 = 12-bit (No averaging, ~532us conversion time)
# 128 = 128 samples averaged (~68ms conversion time)
CFG_ADC_SAMPLES = 1 

# Mode (CONTINUOUS, TRIGGERED, POWERDOWN, ADCOFF)
CFG_MODE = "CONTINUOUS"

# --- CONFIGURATION CALCULATOR ---
def calculate_config_value(rng, gain, samples, mode):
    # Range
    val_rng = 1 if rng == 32 else 0
    
    # Gain
    if gain <= 40: val_pg = 0
    elif gain <= 80: val_pg = 1
    elif gain <= 160: val_pg = 2
    else: val_pg = 3
    
    # ADC (BADC & SADC)
    map_adc = {
        1: 0x3,   # 12-bit, no averaging
        2: 0x9,   # 2 samples
        4: 0xA,   # 4 samples
        8: 0xB,   # 8 samples
        16: 0xC,  # 16 samples
        32: 0xD,  # 32 samples
        64: 0xE,  # 64 samples
        128: 0xF  # 128 samples
    }
    val_adc = map_adc.get(samples, 0x3)
    
    # Mode
    map_mode = {
        "CONTINUOUS": 7,
        "TRIGGERED": 3,
        "POWERDOWN": 0,
        "ADCOFF": 4
    }
    val_mode = map_mode.get(mode, 7)
    
    # Construct 16-bit Config Register
    # Bus Range [13] | Gain [11-12] | BADC [7-10] | SADC [3-6] | Mode [0-2]
    config = (val_rng << 13) | (val_pg << 11) | (val_adc << 7) | (val_adc << 3) | val_mode
    return config

CONFIG_VALUE = calculate_config_value(CFG_BUS_RANGE_V, CFG_GAIN_MV, CFG_ADC_SAMPLES, CFG_MODE) 

# ==========================================
# INA219 CONSTANTS
# ==========================================
REG_CONFIG = 0x00
REG_SHUNT_VOLTAGE = 0x01
REG_BUS_VOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05 

class INA219:
    def __init__(self, address, bus_num=1):
        self.address = address
        self.bus = smbus2.SMBus(bus_num)
        self.current_lsb = 0
        self.power_lsb = 0
        
    def calibrate(self, shunt_ohms, max_expected_amps):
        """
        Calculates and writes the calibration value to the INA219.
        """
        # 1. Determine minimum possible Current LSB to avoid Calibration Register overflow
        #    Cal = 0.04096 / (Current_LSB * Shunt_Resistor)
        #    Max Cal is 65535.
        #    Current_LSB_Min = 0.04096 / (65535 * Shunt_Resistor)
        min_lsb = 0.04096 / (65535 * shunt_ohms)
        
        # 2. Determine User's desired LSB
        vals_lsb = max_expected_amps / 32768.0
        
        # 3. Choose the larger LSB (worst case resolution) to ensure Cal fits in 16-bit
        self.current_lsb = max(vals_lsb, min_lsb)
        
        # 4. Calculate Calibration Register value
        if self.current_lsb > 0 and shunt_ohms > 0:
            cal_value = int(0.04096 / (self.current_lsb * shunt_ohms))
        else:
            cal_value = 0
        
        print("cal_value (pre-clamp):", cal_value, 0.04096 / (self.current_lsb * shunt_ohms), vals_lsb)
        # Clamp strictly to 16-bit (just in case of float rounding edge cases)
        if cal_value > 65535:
            cal_value = 65535
        
        # Power LSB is always 20 * Current LSB
        self.power_lsb = 20 * self.current_lsb
        
        print(f"Calibration Calculation:")
        print(f"  Shunt: {shunt_ohms} Ohms")
        print(f"  Max Amps: {max_expected_amps} A")
        print(f"  Current LSB: {self.current_lsb:.9f} (Required Min: {min_lsb:.9f})")
        print(f"  Cal Value: {cal_value} (0x{cal_value:04x})")

        # Write Calibration Value
        self._write_register(REG_CALIBRATION, cal_value)
        
        # Verify writing (Read back)
        r_cal = self._read_register(REG_CALIBRATION)
        if r_cal != cal_value:
             print(f"  WARNING: Cal Mismatch! Wrote: 0x{cal_value:04x}, Read: 0x{r_cal:04x}")
        
        # Write Config (Resetting or setting specific range)
        self._write_register(REG_CONFIG, CONFIG_VALUE)

    def _write_register(self, reg, value):
        # Swap bytes for Big Endian (INA219 expects MSB first)
        bytes_val = [(value >> 8) & 0xFF, value & 0xFF]
        self.bus.write_i2c_block_data(self.address, reg, bytes_val)

    def _read_register(self, reg):
        # Read 16-bit word, big-endian
        try:
            # smbus read_word_data returns little-endian, so we swap
            raw = self.bus.read_word_data(self.address, reg)
            return ((raw << 8) & 0xFF00) + (raw >> 8)
        except Exception as e:
            print(f"Error reading register 0x{reg:02x}: {e}")
            return 0

    def get_bus_voltage_v(self):
        # Read Bus Voltage Register (0x02)
        # Bits 3-15 are the value (shifted by 3), LSB = 4mV
        raw = self._read_register(REG_BUS_VOLTAGE)
        # Shift right 3 bits to drop status bits, multiply by 4mV (0.004V)
        voltage = (raw >> 3) * 0.004
        return voltage

    def get_shunt_voltage_mv(self):
        # Read Shunt Voltage Register (0x01)
        # The register value is in 10uV units. Signed 16-bit.
        raw = self._read_register(REG_SHUNT_VOLTAGE)
        if raw > 32767:
            raw -= 65536
        return raw * 0.01

    def get_current_ma(self):
        # Read Current Register (0x04)
        # Expects Calibration register to be set correctly
        raw = self._read_register(REG_CURRENT)
        if raw > 32767:
            raw -= 65536
        return raw * self.current_lsb * 1000  # Convert A to mA

    def get_power_mw(self):
        # Read Power Register (0x03)
        # Expects Calibration register to be set correctly
        raw = self._read_register(REG_POWER)
        return raw * self.power_lsb * 1000  # Convert W to mW

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    files = {}
    writers = {}
    
    try:
        sensors = []
        print(f"Initializing {len(INA219_ADDRESSES)} sensors...")
        
        # Initialize and Calibrate all sensors
        for addr in INA219_ADDRESSES:
            print(f"-- Configuring Sensor at 0x{addr:02x} --")
            s = INA219(addr, I2C_BUS_NUMBER)
            s.calibrate(SHUNT_OHMS, MAX_EXPECTED_AMPS)
            sensors.append(s)

        # Setup Logging
        if LOGGING_ENABLED:
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR)
            
            # Create filenames (overwrite existing)
            f_names = {
                'bus_v': f"{LOG_DIR}/log_bus_voltage.csv",
                'current': f"{LOG_DIR}/log_current.csv",
                'power': f"{LOG_DIR}/log_power.csv"
            }
            
            # CSV Headers
            headers = ["Timestamp"] + [f"0x{addr:02x}" for addr in INA219_ADDRESSES]
            
            # Open files and create writers
            for key, fname in f_names.items():
                f = open(fname, 'w', newline='')
                files[key] = f
                w = csv.writer(f)
                w.writerow(headers)
                writers[key] = w
                print(f"Logging {key} to {fname}")

        print("\nStarting Monitoring... (Press Ctrl+C to stop)")
        time.sleep(1) 
        
        print("\nStarting Monitoring... (Press Ctrl+C to stop)")
        time.sleep(1) 
        
        # ============================
        # FAST LOGGING MODE (Buffered)
        # ============================
        if LOGGING_ENABLED:
            print(f"Logging Mode: Buffering raw data into RAM for maximum speed...")
            print("Note: Data will be written to CSV *after* you press Ctrl+C.")
            
            raw_data = []
            
            # Optimization: Use direct method reference and list of addresses
            # Assuming all sensors share the same bus (I2C_BUS_NUMBER)
            read_word = sensors[0].bus.read_word_data
            sensor_addrs = [s.address for s in sensors]
            sensor_map = {s.address: s for s in sensors} # Lookup for LSBs
            
            # Prepare Read Operations based on Config
            # Tuple structure: (Reg Address, Name)
            read_ops = []
            if LOG_READ_SHUNT_VOLTAGE: read_ops.append((0x01, 'shunt'))
            if LOG_READ_BUS_VOLTAGE:   read_ops.append((0x02, 'bus'))
            if LOG_READ_POWER:         read_ops.append((0x03, 'power'))
            if LOG_READ_CURRENT:       read_ops.append((0x04, 'current'))
            
            try:
                while True:
                    t = time.time()
                    for addr in sensor_addrs:
                        try:
                            # Read fields configured by user
                            vals = []
                            for reg, _ in read_ops:
                                vals.append(read_word(addr, reg))
                            
                            raw_data.append((t, addr, tuple(vals)))
                        except Exception:
                            # Ignore I2C errors
                            pass
            
            except KeyboardInterrupt:
                print(f"\nCapture stopped. Processing {len(raw_data)} samples...")
                
                if not os.path.exists(LOG_DIR):
                    os.makedirs(LOG_DIR)
                
                # Open files based on Config
                f_names = {}
                if LOG_READ_BUS_VOLTAGE: f_names['bus'] = f"{LOG_DIR}/log_bus_voltage.csv"
                if LOG_READ_CURRENT:     f_names['current'] = f"{LOG_DIR}/log_current.csv"
                if LOG_READ_POWER:       f_names['power'] = f"{LOG_DIR}/log_power.csv"
                if LOG_READ_SHUNT_VOLTAGE: f_names['shunt'] = f"{LOG_DIR}/log_shunt_voltage.csv"
                
                try:
                    files = {k: open(v, 'w', newline='') for k, v in f_names.items()}
                    writers = {k: csv.writer(v) for k, v in files.items()}
                    
                    # Headers
                    headers = ["Timestamp"] + [f"0x{addr:02x}" for addr in INA219_ADDRESSES]
                    for w in writers.values():
                        w.writerow(headers)
                    
                    print("Converting raw data and saving to CSV...")
                    
                    current_t = -1
                    row_data = {} # {addr: {key: val_str}}
                    
                    def commit_row(timestamp, data):
                        if not data: return
                        
                        ts_str = datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                        
                        # Prepare dictionary of rows to write
                        rows_to_write = {k: [ts_str] for k in writers.keys()}
                        
                        for addr in INA219_ADDRESSES:
                            if addr in data:
                                # Append values
                                for k in writers.keys():
                                    if k in data[addr]:
                                        rows_to_write[k].append(data[addr][k])
                                    else:
                                        rows_to_write[k].append("")
                            else:
                                # Append blanks
                                for k in writers.keys():
                                    rows_to_write[k].append("")
                        
                        # Write to CSVs
                        for k, w in writers.items():
                            w.writerow(rows_to_write[k])

                    # MAP indices from read_ops to clean names
                    op_map_idx = {name: i for i, (_, name) in enumerate(read_ops)}

                    for t, addr, vals in raw_data:
                        if addr in row_data:
                            commit_row(current_t, row_data)
                            row_data = {}
                            current_t = t
                        
                        if current_t == -1:
                            current_t = t
                        
                        sensor_vals = {}
                        
                        # --- Processing Shunt ---
                        if LOG_READ_SHUNT_VOLTAGE:
                            raw = vals[op_map_idx['shunt']]
                            raw = ((raw << 8) & 0xFF00) | (raw >> 8)
                            if raw > 32767: raw -= 65536
                            sensor_vals['shunt'] = f"{raw * 0.01:.4f}"

                        # --- Processing Bus ---
                        if LOG_READ_BUS_VOLTAGE:
                            raw = vals[op_map_idx['bus']]
                            raw = ((raw << 8) & 0xFF00) | (raw >> 8)
                            val = (raw >> 3) * 0.004
                            sensor_vals['bus'] = f"{val:.4f}"

                        # --- Processing Current ---
                        if LOG_READ_CURRENT:
                            raw = vals[op_map_idx['current']]
                            raw = ((raw << 8) & 0xFF00) | (raw >> 8)
                            if raw > 32767: raw -= 65536
                            val = raw * sensor_map[addr].current_lsb * 1000
                            sensor_vals['current'] = f"{val:.4f}"

                        # --- Processing Power ---
                        if LOG_READ_POWER:
                            raw = vals[op_map_idx['power']]
                            raw = ((raw << 8) & 0xFF00) | (raw >> 8)
                            val = raw * sensor_map[addr].power_lsb * 1000
                            sensor_vals['power'] = f"{val:.4f}"
                        
                        row_data[addr] = sensor_vals
                    
                    # Commit last row
                    commit_row(current_t, row_data)
                    
                    print("Done.")
                    
                finally:
                    for f in files.values():
                        f.close()

        # ============================
        # LIVE VIEW MODE (Interactive)
        # ============================
        else:
            # Clear screen once initially
            os.system('clear')
            
            while True:
                # Move cursor to top-left (Home)
                print("\033[H", end="")
                
                now = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                print(f"Update: {now}")
                print("="*65)
                print(f"{'Address':<10} {'Bus (V)':<10} {'Shunt (mV)':<12} {'Current (mA)':<14} {'Power (mW)':<12}")
                print("-" * 65)
                
                for s in sensors:
                    bus_v = s.get_bus_voltage_v()
                    shunt_mv = s.get_shunt_voltage_mv()
                    current_ma = s.get_current_ma()
                    power_mw = s.get_power_mw()

                    print(f"0x{s.address:02x}      {bus_v:<10.3f} {shunt_mv:<12.3f} {current_ma:<14.3f} {power_mw:<12.3f}")
                
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopping.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
