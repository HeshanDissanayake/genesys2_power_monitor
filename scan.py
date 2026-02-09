import smbus2
import time

# Choose the I2C bus number
# On Raspberry Pi, bus 1 is usually used
bus_number = 1
bus = smbus2.SMBus(bus_number)

print("Scanning I2C bus...")

found_devices = []

for address in range(0x03, 0x78):  # Valid I2C addresses are 0x03 to 0x77
    try:
        bus.write_quick(address)
        found_devices.append(hex(address))
    except OSError:
        # No device at this address
        pass

if found_devices:
    print(f"Found I2C devices at addresses: {', '.join(found_devices)}")
else:
    print("No I2C devices found.")

bus.close()
