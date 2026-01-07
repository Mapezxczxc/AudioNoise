import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.widgets import Slider
import os
import argparse

# --- Constants ---
INITIAL_WINDOW_SEC = 2.0
BYTES_PER_SAMPLE = 4
MAX_WIDTH_SEC = 2.0  # Max zoom out

class WaveformVisualizer:
    def __init__(self, filenames, rate, min_zoom_samples=100):
        self.rate = rate
        self.navigating = False
        self.filenames = filenames
        self.min_zoom_samples = min_zoom_samples
        self.min_width_sec = min_zoom_samples / rate

        self.mapped_files = []
        self.lines = []
        self.max_samples = 0

        # Load files
        for f in filenames:
            try:
                fsize = os.path.getsize(f)
                samples = fsize // BYTES_PER_SAMPLE
                mm = np.memmap(f, dtype=np.int32, mode='r', shape=(samples,))
                self.mapped_files.append((mm, os.path.basename(f)))
                self.max_samples = max(self.max_samples, samples)
            except Exception as e:
                print(f"Error opening {f}: {e}")

        if not self.mapped_files:
            return

        self.duration_sec = self.max_samples / self.rate
        self.setup_ui()

    def setup_ui(self):
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        plt.subplots_adjust(bottom=0.2)

        # Create line objects
        for _, name in self.mapped_files:
            line, = self.ax.plot([], [], linewidth=0.8, label=name)
            self.lines.append(line)

        self.ax.grid(True, which='both', linestyle=':', alpha=0.5)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Amplitude")
        self.ax.legend(loc='upper right', fontsize='x-small')

        # Slider setup
        ax_slider = plt.axes([0.15, 0.05, 0.7, 0.03])
        self.slider = Slider(ax_slider, 'Time', 0, self.duration_sec, valinit=0)
        self.slider.on_changed(self.update_slider)

        # Scroll Zoom setup
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        self.ax.callbacks.connect('xlim_changed', self.on_xlim_changed)

        # Enable "Zoom to Rectangle" by default
        try:
            self.fig.canvas.toolbar.zoom()
        except AttributeError:
            pass

        # Initial View
        self.update_view(0, INITIAL_WINDOW_SEC)

        plt.show()

    def get_chunk(self, start_time, window_duration):
        start_sample = int(start_time * self.rate)
        # Ensure we don't request negative start
        start_sample = max(0, start_sample)

        end_sample = int((start_time + window_duration) * self.rate)

        global_min_y, global_max_y = 1e9, -1e9
        has_data = False

        for line, (mm, _) in zip(self.lines, self.mapped_files):
            if start_sample >= mm.size:
                line.set_data([], [])
                continue

            safe_end = min(end_sample, mm.size)
            if safe_end <= start_sample:
                 line.set_data([], [])
                 continue

            chunk = mm[start_sample:safe_end]

            if chunk.size > 0:
                normalized = chunk.astype(np.float32) / 2147483648.0

                # Precise time axis using arange
                t_origin = start_sample / self.rate
                t_axis = np.arange(chunk.size) / self.rate + t_origin

                line.set_data(t_axis, normalized)

                # Show markers if zoomed in enough (few samples visible)
                if chunk.size < 300:
                    line.set_marker('.')
                    line.set_markersize(3)
                else:
                    line.set_marker("")

                global_min_y = min(global_min_y, np.min(normalized))
                global_max_y = max(global_max_y, np.max(normalized))
                has_data = True
            else:
                line.set_data([], [])

        return has_data, global_min_y, global_max_y

    def update_view(self, start_time, width):
        """Core update logic: loads data and sets limits (Constrained Mode)."""
        if self.navigating: return
        self.navigating = True
        try:
            # Clamp width
            width = max(self.min_width_sec, min(width, MAX_WIDTH_SEC))

            # Clamp start time
            start_time = max(0, min(start_time, self.duration_sec))

            has_data, min_y, max_y = self.get_chunk(start_time, width)

            # IMPORTANT: Set limits on the MAIN axes, explicitly using self.ax
            self.ax.set_xlim(start_time, start_time + width)

            # Tight Y-axis scaling logic
            if has_data and max_y > min_y:
                # Symmetric zoom centered at 0
                max_val = max(abs(min_y), abs(max_y))

                if max_val < 1e-6:
                    max_val = 0.01
                else:
                    max_val *= 1.05

                self.ax.set_ylim(-max_val, max_val)
            else:
                 # Default fallback if no data
                 self.ax.set_ylim(-1.0, 1.0)

            self.fig.canvas.draw_idle()
        finally:
            self.navigating = False

    def update_slider(self, val):
        """Callback for slider change."""
        if self.navigating: return

        # Get current width from the main property
        current_xlim = self.ax.get_xlim()
        width = current_xlim[1] - current_xlim[0]

        # Fallback for init
        if width <= 0: width = INITIAL_WINDOW_SEC

        self.update_view(val, width)

    def on_scroll(self, event):
        """Handle zoom."""
        if event.inaxes != self.ax: return

        xlim = self.ax.get_xlim()
        cur_width = xlim[1] - xlim[0]

        scale_factor = 0.8 if event.button == 'up' else 1.2
        new_width = cur_width * scale_factor

        # Clamp zoom
        new_width = max(self.min_width_sec, min(new_width, MAX_WIDTH_SEC))

        # Center zoom
        rel_x = (event.xdata - xlim[0]) / cur_width
        new_start = event.xdata - (new_width * rel_x)

        # Clamp bounds
        new_start = max(0, min(new_start, self.duration_sec - new_width))

        # CRITICAL FIX: Set the plot limits FIRST
        self.ax.set_xlim(new_start, new_start + new_width)

        # Then update slider
        self.slider.set_val(new_start)

    def on_xlim_changed(self, ax):
        """Handle external xlim changes (e.g. from Toolbar). Unconstrained load."""
        if self.navigating: return
        self.navigating = True
        try:
            xlim = ax.get_xlim()
            start_time = xlim[0]
            width = xlim[1] - xlim[0]

            # Reload data (No constraints)
            self.get_chunk(start_time, width)

            # Sync slider (silently hopefully)
            if hasattr(self, 'slider'):
                self.slider.set_val(start_time)
        finally:
            self.navigating = False

    def on_key(self, event):
        """Handle keyboard shortcuts (Independent Navigation)."""
        if self.navigating: return
        self.navigating = True
        try:
            # Get properties
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()

            width = xlim[1] - xlim[0]
            height = ylim[1] - ylim[0]

            changed = False

            if event.key == 'right':
                shift = width * 0.25
                self.ax.set_xlim(xlim[0] + shift, xlim[1] + shift)
                changed = True
            elif event.key == 'left':
                shift = width * 0.25
                self.ax.set_xlim(xlim[0] - shift, xlim[1] - shift)
                changed = True
            elif event.key == 'up':
                shift = height * 0.25
                self.ax.set_ylim(ylim[0] + shift, ylim[1] + shift)
                changed = True
            elif event.key == 'down':
                shift = height * 0.25
                self.ax.set_ylim(ylim[0] - shift, ylim[1] - shift)
                changed = True

            if changed:
                # Reload data for new X view
                # We need new xlim
                new_xlim = self.ax.get_xlim()
                self.get_chunk(new_xlim[0], new_xlim[1] - new_xlim[0])
                self.slider.set_val(new_xlim[0])
                self.fig.canvas.draw_idle()

        finally:
             self.navigating = False

        # Space Bar (Reset Zoom) - Needs update_view which handles navigating flag internally
        if event.key == ' ':
            current_xlim = self.ax.get_xlim()
            center = (current_xlim[0] + current_xlim[1]) / 2
            new_width = MAX_WIDTH_SEC
            new_start = center - (new_width / 2)
            self.update_view(new_start, new_width)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Linux Audio Waveform Visualizer 2026 (mmap)")
    parser.add_argument('files', nargs='+', help="Input .bin files (int32)")
    parser.add_argument('--rate', type=int, default=48000, help="Sample rate (Hz)")
    parser.add_argument('--min-zoom-samples', type=int, default=100, help="Minimum samples to show when zoomed in")
    args = parser.parse_args()

    app = WaveformVisualizer(args.files, args.rate, args.min_zoom_samples)
