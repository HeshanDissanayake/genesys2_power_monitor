import pandas as pd
import matplotlib.pyplot as plt
import glob
import os
import sys

# Directory containing logs
LOG_DIR = "logs"

def get_latest_log_files():
    """Finds the most recent set of log files in the log directory."""
    if not os.path.exists(LOG_DIR):
        print(f"Error: Directory '{LOG_DIR}' not found.")
        return []

    # Get all csv files
    files = glob.glob(os.path.join(LOG_DIR, "*.csv"))
    if not files:
        print("No log files found.")
        return []

    # Sort by modification time
    files.sort(key=os.path.getmtime, reverse=True)
    
    # Priority: Check for non-timestamped files (latest versions)
    static_files = [
        os.path.join(LOG_DIR, "log_bus_voltage.csv"),
        os.path.join(LOG_DIR, "log_current.csv"),
        os.path.join(LOG_DIR, "log_power.csv")
    ]
    existing_static = [f for f in static_files if os.path.exists(f)]
    
    # If we have recently modified static files (e.g. within last minute of the latest file), use them.
    # Or simply: if static files exist, return them. 
    if existing_static:
        return existing_static

    # Fallback to timestamp logic for older files
    latest_file = files[0]
    # Extract timestamp part (last part before extension)
    # format: log_bus_voltage_20260210_104809.csv
    try:
        base_name = os.path.basename(latest_file)
        # split by underscore, take last two parts (date_time) and remove extension
        parts = base_name.replace('.csv', '').split('_')
        timestamp_str = f"{parts[-2]}_{parts[-1]}"
        
        matching_files = [f for f in files if timestamp_str in f]
        return matching_files
    except:
        return [latest_file]

def plot_file(filepath):
    """Reads a CSV log file and generates a plot."""
    try:
        print(f"Processing {filepath}...")
        df = pd.read_csv(filepath)
        
        # Check if empty
        if df.empty:
            print(f"Skipping empty file: {filepath}")
            return

        # Convert Timestamp to datetime objects
        # Format is HH:MM:S.f (no date), so we attach dummy date to handle parsing
        # But pandas to_datetime is smart enough for calculation if we just want relative time
        try:
            # We explicitly tell pandas the format to be safe, or let it infer
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='%H:%M:%S.%f')
        except ValueError:
            # Fallback for standard ISO or mixed formats
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])

        # Calculate relative time in seconds from start
        start_time = df['Timestamp'].iloc[0]
        df['Time_Sec'] = (df['Timestamp'] - start_time).dt.total_seconds()

        # Create output directory for plots
        plot_dir = os.path.join(LOG_DIR, "plots")
        if not os.path.exists(plot_dir):
            os.makedirs(plot_dir)

        # Plot each column separately
        data_cols = [c for c in df.columns if c not in ['Timestamp', 'Time_Sec']]
        
        filename = os.path.basename(filepath)
        file_root = filename.replace('.csv', '')
        
        # Determine labels based on filename
        title_type = "Unknown"
        ylabel = "Value"
        if "bus_voltage" in filename:
            title_type = "Bus Voltage"
            ylabel = "Voltage (V)"
        elif "current" in filename:
            title_type = "Current"
            ylabel = "Current (mA)"
        elif "power" in filename:
            title_type = "Power"
            ylabel = "Power (mW)"

        for col in data_cols:
            plt.figure(figsize=(10, 6))
            plt.plot(df['Time_Sec'], df[col], label=col, linewidth=1.5, color='tab:blue')
            
            plt.title(f"{title_type}: {col}")
            plt.xlabel("Time (seconds)")
            plt.ylabel(ylabel)
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.legend()
            
            # Save plot to submenu
            clean_col_name = col.replace(" ", "_").replace("(", "").replace(")", "")
            output_filename = os.path.join(plot_dir, f"{file_root}_{clean_col_name}.png")
            plt.savefig(output_filename, dpi=150)
            plt.close()
            print(f"  Saved: {output_filename}")

    except Exception as e:
        print(f"Failed to plot {filepath}: {e}")

if __name__ == "__main__":
    # Check if files provided as arguments
    if len(sys.argv) > 1:
        log_files = sys.argv[1:]
    else:
        # Scan for latest
        log_files = get_latest_log_files()

    if not log_files:
        print("No files to plot.")
    else:
        print(f"Plotting files: {log_files}")
        for f in log_files:
            plot_file(f)
