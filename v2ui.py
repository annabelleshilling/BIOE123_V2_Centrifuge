"""
Centrifuge Control System - Frontend UI with Arduino Communication
Updated version with serial communication
"""

import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import json
import time
import threading


class CentrifugeUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Spin Coaster Centrifuge Control")
        self.root.geometry("800x650")
        self.root.configure(bg='#f0f0f0')

        # Serial communication
        self.serial_port = None
        self.serial_connected = False
        self.serial_thread = None
        self.running_thread = True

        # State variables
        self.target_rpm = tk.IntVar(value=0)
        self.current_rpm = tk.IntVar(value=0)
        self.target_duration_sec = tk.IntVar(value=0)
        self.remaining_time_sec = tk.IntVar(value=0)
        self.state = tk.StringVar(value="DISCONNECTED")
        self.is_running = False

        # Safety status
        self.lid_closed = tk.BooleanVar(value=False)
        self.system_level = tk.BooleanVar(value=False)

        # Build UI
        self._create_connection_bar()
        self._create_header()
        self._create_status_display()
        self._create_rpm_controls()
        self._create_duration_controls()
        self._create_action_buttons()
        self._create_safety_indicators()

        # Try to auto-connect
        self.root.after(100, self._auto_connect)

    def _create_connection_bar(self):
        """Create connection status bar"""
        conn_frame = tk.Frame(self.root, bg='#34495e', height=35)
        conn_frame.pack(fill='x', padx=0, pady=0)
        conn_frame.pack_propagate(False)

        tk.Label(
            conn_frame,
            text="Arduino:",
            font=('Arial', 10),
            bg='#34495e',
            fg='white'
        ).pack(side='left', padx=10)

        self.conn_status = tk.Label(
            conn_frame,
            text="Not Connected",
            font=('Arial', 10, 'bold'),
            bg='#34495e',
            fg='#e74c3c'
        )
        self.conn_status.pack(side='left', padx=5)

        self.connect_btn = tk.Button(
            conn_frame,
            text="Connect",
            command=self._connect_arduino,
            font=('Arial', 9),
            bg='#2ecc71',
            fg='white',
            width=10,
            cursor='hand2'
        )
        self.connect_btn.pack(side='right', padx=10, pady=5)

    def _create_header(self):
        """Create header section"""
        header_frame = tk.Frame(self.root, bg='#2c3e50', height=70)
        header_frame.pack(fill='x', padx=0, pady=0)
        header_frame.pack_propagate(False)

        title = tk.Label(
            header_frame,
            text="🌀 Spin Coaster Centrifuge",
            font=('Arial', 22, 'bold'),
            bg='#2c3e50',
            fg='white'
        )
        title.pack(pady=15)

    def _create_status_display(self):
        """Create real-time status display"""
        status_frame = tk.LabelFrame(
            self.root,
            text="System Status",
            font=('Arial', 12, 'bold'),
            bg='#f0f0f0',
            padx=20,
            pady=15
        )
        status_frame.pack(fill='x', padx=20, pady=10)

        # Current RPM display
        rpm_display_frame = tk.Frame(status_frame, bg='#f0f0f0')
        rpm_display_frame.pack(side='left', padx=30)

        tk.Label(
            rpm_display_frame,
            text="Current Speed",
            font=('Arial', 10),
            bg='#f0f0f0',
            fg='#555'
        ).pack()

        self.rpm_label = tk.Label(
            rpm_display_frame,
            textvariable=self.current_rpm,
            font=('Arial', 48, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        )
        self.rpm_label.pack()

        tk.Label(
            rpm_display_frame,
            text="RPM",
            font=('Arial', 12),
            bg='#f0f0f0',
            fg='#555'
        ).pack()

        # Time remaining display
        time_display_frame = tk.Frame(status_frame, bg='#f0f0f0')
        time_display_frame.pack(side='left', padx=30)

        tk.Label(
            time_display_frame,
            text="Time Remaining",
            font=('Arial', 10),
            bg='#f0f0f0',
            fg='#555'
        ).pack()

        self.time_label = tk.Label(
            time_display_frame,
            text="00:00",
            font=('Arial', 36, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        )
        self.time_label.pack()

        # State indicator
        state_frame = tk.Frame(status_frame, bg='#f0f0f0')
        state_frame.pack(side='left', padx=30)

        tk.Label(
            state_frame,
            text="Status",
            font=('Arial', 10),
            bg='#f0f0f0',
            fg='#555'
        ).pack()

        self.state_label = tk.Label(
            state_frame,
            textvariable=self.state,
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0',
            fg='#95a5a6'
        )
        self.state_label.pack()

    def _create_rpm_controls(self):
        """Create RPM setting controls"""
        rpm_frame = tk.LabelFrame(
            self.root,
            text="Speed Control (RPM)",
            font=('Arial', 12, 'bold'),
            bg='#f0f0f0',
            padx=20,
            pady=15
        )
        rpm_frame.pack(fill='x', padx=20, pady=10)

        # Preset buttons
        preset_frame = tk.Frame(rpm_frame, bg='#f0f0f0')
        preset_frame.pack(pady=5)

        tk.Label(
            preset_frame,
            text="Quick Presets:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left', padx=5)

        presets = [50, 100, 500, 1000, 1500, 2000, 2500]
        for rpm in presets:
            btn = tk.Button(
                preset_frame,
                text=f"{rpm}",
                command=lambda r=rpm: self.set_rpm(r),
                width=6,
                font=('Arial', 9),
                bg='#3498db',
                fg='white',
                relief='raised',
                cursor='hand2'
            )
            btn.pack(side='left', padx=3)

        # Manual input
        manual_frame = tk.Frame(rpm_frame, bg='#f0f0f0')
        manual_frame.pack(pady=10)

        tk.Label(
            manual_frame,
            text="Set RPM (0-3000):",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left', padx=5)

        self.rpm_entry = tk.Entry(
            manual_frame,
            font=('Arial', 12),
            width=10,
            justify='center'
        )
        self.rpm_entry.pack(side='left', padx=5)
        self.rpm_entry.insert(0, "0")

        tk.Button(
            manual_frame,
            text="Set",
            command=self.set_rpm_from_entry,
            font=('Arial', 10),
            bg='#2ecc71',
            fg='white',
            width=8,
            cursor='hand2'
        ).pack(side='left', padx=5)

        # Target display
        tk.Label(
            rpm_frame,
            text="Target:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left')

        tk.Label(
            rpm_frame,
            textvariable=self.target_rpm,
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0',
            fg='#e74c3c'
        ).pack(side='left', padx=5)

        tk.Label(
            rpm_frame,
            text="RPM",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left')

    def _create_duration_controls(self):
        """Create duration setting controls"""
        duration_frame = tk.LabelFrame(
            self.root,
            text="Duration Control",
            font=('Arial', 12, 'bold'),
            bg='#f0f0f0',
            padx=20,
            pady=15
        )
        duration_frame.pack(fill='x', padx=20, pady=10)

        # Preset time buttons
        preset_frame = tk.Frame(duration_frame, bg='#f0f0f0')
        preset_frame.pack(pady=5)

        tk.Label(
            preset_frame,
            text="Quick Presets:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left', padx=5)

        time_presets = [
            ("5s", 5), ("10s", 10), ("30s", 30),
            ("1 min", 60), ("2 min", 120), ("5 min", 300), ("10 min", 600)
        ]

        for label, seconds in time_presets:
            btn = tk.Button(
                preset_frame,
                text=label,
                command=lambda s=seconds: self.set_duration(s),
                width=6,
                font=('Arial', 9),
                bg='#9b59b6',
                fg='white',
                relief='raised',
                cursor='hand2'
            )
            btn.pack(side='left', padx=3)

        # Manual input
        manual_frame = tk.Frame(duration_frame, bg='#f0f0f0')
        manual_frame.pack(pady=10)

        tk.Label(
            manual_frame,
            text="Minutes:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left', padx=5)

        self.min_entry = tk.Entry(manual_frame, font=('Arial', 12), width=5, justify='center')
        self.min_entry.pack(side='left', padx=2)
        self.min_entry.insert(0, "0")

        tk.Label(
            manual_frame,
            text="Seconds:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left', padx=5)

        self.sec_entry = tk.Entry(manual_frame, font=('Arial', 12), width=5, justify='center')
        self.sec_entry.pack(side='left', padx=2)
        self.sec_entry.insert(0, "0")

        tk.Button(
            manual_frame,
            text="Set Duration",
            command=self.set_duration_from_entry,
            font=('Arial', 10),
            bg='#2ecc71',
            fg='white',
            width=12,
            cursor='hand2'
        ).pack(side='left', padx=10)

        # Target display
        tk.Label(
            duration_frame,
            text="Target Duration:",
            font=('Arial', 10),
            bg='#f0f0f0'
        ).pack(side='left')

        self.duration_display = tk.Label(
            duration_frame,
            text="00:00",
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0',
            fg='#e74c3c'
        )
        self.duration_display.pack(side='left', padx=5)

    def _create_action_buttons(self):
        """Create START/STOP buttons"""
        action_frame = tk.Frame(self.root, bg='#f0f0f0')
        action_frame.pack(fill='x', padx=20, pady=20)

        self.start_btn = tk.Button(
            action_frame,
            text="▶ START",
            command=self.start_centrifuge,
            font=('Arial', 16, 'bold'),
            bg='#27ae60',
            fg='white',
            height=2,
            width=15,
            relief='raised',
            cursor='hand2',
            state='disabled'
        )
        self.start_btn.pack(side='left', padx=20, expand=True)

        self.stop_btn = tk.Button(
            action_frame,
            text="⬛ STOP",
            command=self.stop_centrifuge,
            font=('Arial', 16, 'bold'),
            bg='#e74c3c',
            fg='white',
            height=2,
            width=15,
            relief='raised',
            cursor='hand2',
            state='disabled'
        )
        self.stop_btn.pack(side='left', padx=20, expand=True)

    def _create_safety_indicators(self):
        """Create safety status indicators"""
        safety_frame = tk.LabelFrame(
            self.root,
            text="Safety Status",
            font=('Arial', 10, 'bold'),
            bg='#f0f0f0',
            padx=15,
            pady=10
        )
        safety_frame.pack(fill='x', padx=20, pady=5)

        # Lid status
        self.lid_indicator = tk.Label(
            safety_frame,
            text="🔒 Lid: Checking...",
            font=('Arial', 9),
            bg='#f0f0f0',
            fg='#95a5a6'
        )
        self.lid_indicator.pack(side='left', padx=15)

        # Level status
        self.level_indicator = tk.Label(
            safety_frame,
            text="📍 Level: Checking...",
            font=('Arial', 9),
            bg='#f0f0f0',
            fg='#95a5a6'
        )
        self.level_indicator.pack(side='left', padx=15)

    # ==================== ARDUINO COMMUNICATION ====================
    def _auto_connect(self):
        """Try to automatically find and connect to Arduino"""
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if 'Arduino' in port.description or 'USB' in port.description:
                try:
                    self._connect_to_port(port.device)
                    return
                except:
                    pass
        # If auto-connect fails, enable manual connect button
        self.connect_btn.config(state='normal')

    def _connect_arduino(self):
        """Manual connection to Arduino"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            messagebox.showerror("Error", "No serial ports found")
            return

        # Simple port selection (in production, use a dropdown)
        port = ports[0].device
        self._connect_to_port(port)

    def _connect_to_port(self, port_name):
        """Connect to specific port"""
        try:
            self.serial_port = serial.Serial(port_name, 115200, timeout=1)
            time.sleep(2)  # Wait for Arduino to reset

            self.serial_connected = True
            self.conn_status.config(text=f"Connected: {port_name}", fg='#27ae60')
            self.connect_btn.config(state='disabled')
            self.start_btn.config(state='normal')

            # Start serial reading thread
            self.serial_thread = threading.Thread(target=self._read_serial, daemon=True)
            self.serial_thread.start()

            # Start ping thread for watchdog
            threading.Thread(target=self._ping_watchdog, daemon=True).start()

        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")

    def _read_serial(self):
        """Read serial data in background thread"""
        while self.running_thread and self.serial_connected:
            try:
                if self.serial_port and self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8').strip()

                    # Parse JSON status updates
                    if line.startswith('{'):
                        try:
                            data = json.loads(line)
                            self.root.after(0, lambda: self._update_from_arduino(data))
                        except json.JSONDecodeError:
                            pass

                    # Handle text responses
                    elif line.startswith('STATE:'):
                        state = line.split(':')[1]
                        self.root.after(0, lambda s=state: self.state.set(s))

                    elif line.startswith('ERROR:'):
                        error = line.split(':')[1]
                        self.root.after(0, lambda e=error: messagebox.showerror("Arduino Error", e))

                    elif line.startswith('STATUS:COMPLETE'):
                        self.root.after(0, self._handle_completion)

                time.sleep(0.05)  # Small delay to prevent CPU hogging

            except Exception as e:
                print(f"Serial read error: {e}")
                self.serial_connected = False

    def _ping_watchdog(self):
        """Send periodic ping to Arduino watchdog"""
        while self.running_thread and self.serial_connected:
            try:
                if self.serial_port:
                    self.serial_port.write(b'PING\n')
                time.sleep(2)  # Ping every 2 seconds
            except:
                pass

    def _update_from_arduino(self, data):
        """Update UI from Arduino status data"""
        if 'currentRPM' in data:
            self.current_rpm.set(data['currentRPM'])

        if 'state' in data:
            self.state.set(data['state'])
            self._update_state_color(data['state'])

        if 'lidClosed' in data:
            lid_closed = data['lidClosed']
            color = '#27ae60' if lid_closed else '#e74c3c'
            text = f"🔒 Lid: {'Closed' if lid_closed else 'Open'}"
            self.lid_indicator.config(text=text, fg=color)

        if 'level' in data:
            level = data['level']
            color = '#27ae60' if level else '#e74c3c'
            text = f"📍 Level: {'OK' if level else 'Tilted'}"
            self.level_indicator.config(text=text, fg=color)

        if 'remainingMs' in data:
            remaining_sec = data['remainingMs'] // 1000
            mins = remaining_sec // 60
            secs = remaining_sec % 60
            self.time_label.config(text=f"{mins:02d}:{secs:02d}")

    def _update_state_color(self, state):
        """Update state label color based on state"""
        color_map = {
            'IDLE': '#27ae60',
            'RAMPING_UP': '#f39c12',
            'RUNNING': '#27ae60',
            'RAMPING_DOWN': '#e67e22',
            'ERROR': '#e74c3c'
        }
        self.state_label.config(fg=color_map.get(state, '#95a5a6'))

    def _handle_completion(self):
        """Handle centrifugation completion"""
        self.is_running = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        messagebox.showinfo("Complete", "Centrifugation complete. Safe to remove samples.")

    # ==================== CONTROL METHODS ====================
    def set_rpm(self, rpm):
        """Set target RPM"""
        if not self.is_running:
            self.target_rpm.set(rpm)
            self.rpm_entry.delete(0, tk.END)
            self.rpm_entry.insert(0, str(rpm))
        else:
            messagebox.showwarning("Warning", "Cannot change RPM while running")

    def set_rpm_from_entry(self):
        """Set RPM from manual entry"""
        if not self.is_running:
            try:
                rpm = int(self.rpm_entry.get())
                if 0 <= rpm <= 3000:
                    self.target_rpm.set(rpm)
                else:
                    messagebox.showerror("Error", "RPM must be 0-3000")
            except ValueError:
                messagebox.showerror("Error", "Invalid number")
        else:
            messagebox.showwarning("Warning", "Cannot change RPM while running")

    def set_duration(self, seconds):
        """Set duration from preset"""
        if not self.is_running:
            self.target_duration_sec.set(seconds)
            mins = seconds // 60
            secs = seconds % 60
            self.duration_display.config(text=f"{mins:02d}:{secs:02d}")
        else:
            messagebox.showwarning("Warning", "Cannot change duration while running")

    def set_duration_from_entry(self):
        """Set duration from manual entry"""
        if not self.is_running:
            try:
                mins = int(self.min_entry.get())
                secs = int(self.sec_entry.get())
                total = mins * 60 + secs

                if total <= 600:
                    self.set_duration(total)
                else:
                    messagebox.showerror("Error", "Duration cannot exceed 10 min")
            except ValueError:
                messagebox.showerror("Error", "Invalid numbers")
        else:
            messagebox.showwarning("Warning", "Cannot change duration while running")

    def start_centrifuge(self):
        """Start centrifuge"""
        if not self.serial_connected:
            messagebox.showerror("Error", "Arduino not connected")
            return

        if self.target_rpm.get() == 0:
            messagebox.showerror("Error", "Set target RPM")
            return

        if self.target_duration_sec.get() == 0:
            messagebox.showerror("Error", "Set duration")
            return

        response = messagebox.askyesno(
            "Confirm Start",
            f"Start at {self.target_rpm.get()} RPM for {self.target_duration_sec.get()}s?"
        )

        if response:
            # Send START command to Arduino
            duration_ms = self.target_duration_sec.get() * 1000
            cmd = f"START:{self.target_rpm.get()}:{duration_ms}\n"
            self.serial_port.write(cmd.encode())

            self.is_running = True
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')

    def stop_centrifuge(self):
        """Stop centrifuge"""
        response = messagebox.askyesno(
            "Confirm Stop",
            "Stop and begin ramp-down?"
        )

        if response:
            self.serial_port.write(b'STOP\n')

    def __del__(self):
        """Cleanup on exit"""
        self.running_thread = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()


def main():
    root = tk.Tk()
    app = CentrifugeUI(root)

    def on_closing():
        app.running_thread = False
        if app.serial_port and app.serial_port.is_open:
            app.serial_port.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()