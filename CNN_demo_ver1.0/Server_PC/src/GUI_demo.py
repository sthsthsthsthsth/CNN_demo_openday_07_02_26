import tkinter as tk
from tkinter import ttk
import serial
import numpy as np
try:
    import tensorflow as tf
except ImportError:
    tf = None
import threading
import queue
import time
import random
import ctypes   # For OS Master volume control
import winsound # For native sound actions (Windows)
import os

SOUND_src = '.../sfx'
MODEL_src = '.../model'

try:
    if tf is not None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_model_path = os.path.join(script_dir, os.path.join(MODEL_src,"minimal_mnist_model.keras"))
        if os.path.exists(local_model_path):
            model = tf.keras.models.load_model(local_model_path)
        else:
            print("WARNING: Could not load model!")
    else:
        model = None
except Exception as e:
    print(f"Could not load model, using mock predictions for testing: {e}")
    model = None

GRID_SIZE = 28
PAYLOAD_SIZE = GRID_SIZE * GRID_SIZE
SERIAL_PORT = 'COM6'
BAUD_RATE = 115200


BG_COLORS = ["#FF5733", "#33FF57", "#3357FF", "#F3FF33", "#FF33F3", "#33FFF0", "#FFA500", "#8A2BE2", "#00EDFF", "#7FFF00"]

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CNN Demo")
        
        # --- FULLSCREEN CONFIGURATION ---
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False)) 
        self.configure(bg="#222222")
        
        # Thread communication queue
        self.queue = queue.Queue()
        
        # Application state variables
        self.current_screen = "menu"
        self.selected_menu_idx = 0  
        self.sound_val = 50
        
        # Copycat Game Variables
        self.copycat_sequence = []
        self.copycat_user_sequence = []
        self.copycat_state = "idle" 
        self.copycat_level = 1
        self.copycat_timer_left = 60
        self.timer_job = None
        self.transition_job = None  # Track state transitions to cancel on reset
        self.anim_job = None  # Track prediction screen animation ticks
        
        # Mini-menu (Pause) State Variables
        self.is_paused = False
        self.pause_selected_idx = 0 
        self.pause_overlay = None

        # Build initial main menu
        self.create_main_menu()
        
        # Keyboard binds for testing/GUI navigation
        self.bind("<o>", lambda e: self.queue.put(("CMD", "o")))
        self.bind("<x>", lambda e: self.queue.put(("CMD", "x")))
        self.bind("<Return>", lambda e: self.queue.put(("CMD", "x")))
        self.bind("<space>", lambda e: self.queue.put(("CMD", "o")))
        self.bind("<Up>", lambda e: self.queue.put(("CMD", "up")))
        self.bind("<Down>", lambda e: self.queue.put(("CMD", "down")))
        self.bind("<Left>", lambda e: self.queue.put(("CMD", "left")))
        self.bind("<Right>", lambda e: self.queue.put(("CMD", "right")))
        
        # Start Serial Background Thread
        self.is_listening = True
        self.serial_thread = threading.Thread(target=self.serial_listener, daemon=True)
        self.serial_thread.start()
        
        # Start checking queue for serial events
        self.check_queue()

    # ------------------ SOUND CONTROLS ------------------

    def play_action_sound(self, sound_type):
        """Centralized helper to play specific sounds across the app"""
        try:
            if sound_type == "navigate":
                winsound.PlaySound(os.path.join(SOUND_src,'pokemon_a_button_gba.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif sound_type == "select":
                winsound.PlaySound(os.path.join(SOUND_src,'2020-08-20-00-00-28.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif sound_type == "correct":
                winsound.PlaySound(os.path.join(SOUND_src,'2020-08-20-00-00-28.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif sound_type == "wrong":
                winsound.PlaySound(os.path.join(SOUND_src,'1-38.Lose.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif sound_type == "jackpot":
                winsound.PlaySound(os.path.join(SOUND_src,'1-40. Jackpot.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"Sound play error: {e}")

    def apply_system_sound(self):
        """Adjusts the master volume of the host OS"""
        try:
            volume_level = int((self.sound_val / 100.0) * 0xFFFF)
            ctypes.windll.winmm.waveOutSetVolume(0, volume_level | (volume_level << 16))
            print(f"[APP SYSTEM] Master system volume set to {self.sound_val}%")
        except Exception as e:
            print(f"[APP SYSTEM] Volume control failed: {e}")

    # ------------------ UI SCREENS ------------------
    
    def clear_screen(self):
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        if self.transition_job:
            self.after_cancel(self.transition_job)
            self.transition_job = None
        if hasattr(self, 'anim_job') and self.anim_job:
            self.after_cancel(self.anim_job)
            self.anim_job = None
        for widget in self.winfo_children():
            if widget != self.pause_overlay:
                widget.destroy()

    def create_main_menu(self):
        self.current_screen = "menu"
        self.is_paused = False
        self.clear_screen()
        
        main_frame = tk.Frame(self, bg="#222222")
        main_frame.pack(expand=True, fill="both")
        
        title = tk.Label(main_frame, text="MAIN MENU", font=("Helvetica", 36, "bold"), bg="#222222", fg="white")
        title.pack(pady=60)
        
        self.menu_buttons = []
        options = [("Number Prediction", self.start_number_prediction), 
                   ("Copycat Game", self.start_copycat), 
                   ("Configuration", self.start_config)]
        
        for idx, (text, cmd) in enumerate(options):
            btn = tk.Button(main_frame, text=text, font=("Helvetica", 20), width=25, height=2, command=cmd,
                            bg="#444444", fg="white", activebackground="#666666", activeforeground="white")
            btn.pack(pady=15)
            self.menu_buttons.append(btn)
            
        # Add instruction text below menu options
        info_label = tk.Label(main_frame, text="O SELECT    X ENTER", font=("Helvetica", 20, "bold"), bg="#222222", fg="#888888")
        info_label.pack(pady=40)
            
        self.update_menu_highlight()

    def update_menu_highlight(self):
        for idx, btn in enumerate(self.menu_buttons):
            if idx == self.selected_menu_idx:
                btn.config(bg="#007ACC", fg="white", relief="sunken")
            else:
                btn.config(bg="#444444", fg="white", relief="raised")

    def start_number_prediction(self):
        self.play_action_sound("navigate")
        self.current_screen = "prediction"
        self.is_paused = False
        self.clear_screen()
        
        self.pred_bg_frame = tk.Frame(self, bg="#222222")
        self.pred_bg_frame.pack(fill="both", expand=True)
        
        title_label = tk.Label(self.pred_bg_frame, text="Neural Network Visualization", font=("Helvetica", 28, "bold"), bg="#222222", fg="white")
        title_label.pack(pady=10)
        
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        canvas_w = int(screen_w * 0.95)
        canvas_h = int(screen_h * 0.70)
        
        self.pred_canvas = tk.Canvas(self.pred_bg_frame, width=canvas_w, height=canvas_h, bg="#222222", highlightthickness=0)
        self.pred_canvas.pack(pady=10)
        self.pred_canvas.create_text(canvas_w // 2, canvas_h // 2, text="Waiting for digit input...", font=("Helvetica", 32, "bold"), fill="#888888")
        
        btn_frame = tk.Frame(self.pred_bg_frame, bg="#222222")
        btn_frame.pack(pady=10)
        
        self.btn_pause = tk.Button(btn_frame, text="O Pause", font=("Helvetica", 18, "bold"),
                                   bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                   width=12, height=1, command=self.show_pause_menu, relief="flat", bd=0, highlightthickness=0)
        self.btn_pause.pack(pady=10)

    def start_copycat(self):
        self.play_action_sound("navigate")
        self.current_screen = "copycat"
        self.is_paused = False
        self.clear_screen()
        
        self.copycat_level = 1
        self.copycat_timer_left = 60
        self.copycat_sequence = []
        
        container = tk.Frame(self, bg="#222222")
        container.pack(expand=True)
        
        self.cc_status_label = tk.Label(container, text="Level 1: Prepare!", font=("Helvetica", 36, "bold"), bg="#222222", fg="white")
        self.cc_status_label.pack(pady=25)
        
        self.cc_timer_label = tk.Label(container, text="Time: 60s", font=("Helvetica", 28), bg="#222222", fg="#E06C75")
        self.cc_timer_label.pack(pady=15)
        
        self.cc_display_label = tk.Label(container, text="---", font=("Helvetica", 150, "bold"), bg="#333333", fg="yellow", width=6, height=2)
        self.cc_display_label.pack(pady=35)
        
        # Display the last user input on the middle top left
        self.cc_input_label = tk.Label(self, text="Input Number: -", font=("Helvetica", 24, "bold"), bg="#222222", fg="#888888")
        self.cc_input_label.place(relx=0.08, rely=0.3, anchor="w")
        
        btn_frame = tk.Frame(container, bg="#222222")
        btn_frame.pack(pady=35)
        
        self.btn_pause = tk.Button(btn_frame, text="O Pause", font=("Helvetica", 18, "bold"),
                                   bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                   width=12, height=1, command=self.show_pause_menu, relief="flat", bd=0, highlightthickness=0)
        self.btn_pause.pack(side="left", padx=20)
        
        self.btn_reset = tk.Button(btn_frame, text="X Reset", font=("Helvetica", 18, "bold"),
                                   bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                   width=12, height=1, command=self.start_copycat, relief="flat", bd=0, highlightthickness=0)
        self.btn_reset.pack(side="left", padx=20)
        
        self.transition_job = self.after(1500, self.next_copycat_level)

    def start_config(self):
        self.play_action_sound("navigate")
        self.current_screen = "config"
        self.is_paused = False
        self.clear_screen()
        
        container = tk.Frame(self, bg="#222222")
        container.pack(expand=True)
        
        tk.Label(container, text="Settings", font=("Helvetica", 36, "bold"), bg="#222222", fg="white").pack(pady=40)
        
        # Volume display
        self.vol_display_label = tk.Label(container, text=f"Volume: {int(self.sound_val)}%", font=("Helvetica", 28, "bold"), bg="#222222", fg="white")
        self.vol_display_label.pack(pady=15)
        
        # +/- Buttons Frame
        adjust_frame = tk.Frame(container, bg="#222222")
        adjust_frame.pack(pady=15)
        
        # Style them as sleek gray transparent blocks
        self.btn_minus = tk.Button(adjust_frame, text="-", font=("Helvetica", 24, "bold"),
                                   bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                   width=4, height=1, command=self.decrease_volume, relief="flat", bd=0, highlightthickness=0)
        self.btn_minus.pack(side="left", padx=15)
        
        self.btn_plus = tk.Button(adjust_frame, text="+", font=("Helvetica", 24, "bold"),
                                   bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                   width=4, height=1, command=self.increase_volume, relief="flat", bd=0, highlightthickness=0)
        self.btn_plus.pack(side="left", padx=15)
        
        # Save & Exit Button
        self.btn_save_exit = tk.Button(container, text="Save & Exit", font=("Helvetica", 18, "bold"),
                                       bg="#333333", fg="white", activebackground="#444444", activeforeground="white",
                                       width=18, height=1, command=self.save_and_return_config, relief="flat", bd=0, highlightthickness=0)
        self.btn_save_exit.pack(pady=40)
        
        self.config_selected_idx = 2  # Default to Save & Exit
        self.update_config_highlight()

    def decrease_volume(self):
        self.play_action_sound("navigate")
        self.sound_val = max(0, self.sound_val - 10)
        self.vol_display_label.config(text=f"Volume: {int(self.sound_val)}%")
        try:
            # Simulate 5 VK_VOLUME_DOWN key presses to decrease master volume by 10%
            for _ in range(5):
                ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        except Exception as e:
            print(f"[Volume] Keystroke simulation failed: {e}")
        self.update_config_highlight()

    def increase_volume(self):
        self.play_action_sound("navigate")
        self.sound_val = min(100, self.sound_val + 10)
        self.vol_display_label.config(text=f"Volume: {int(self.sound_val)}%")
        try:
            # Simulate 5 VK_VOLUME_UP key presses to increase master volume by 10%
            for _ in range(5):
                ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        except Exception as e:
            print(f"[Volume] Keystroke simulation failed: {e}")
        self.update_config_highlight()

    def update_config_highlight(self):
        buttons = [self.btn_minus, self.btn_plus, self.btn_save_exit]
        for idx, btn in enumerate(buttons):
            if idx == self.config_selected_idx:
                btn.config(bg="#444444", fg="yellow")
            else:
                btn.config(bg="#333333", fg="white")

    def save_and_return_config(self):
        self.apply_system_sound()
        self.play_action_sound("select")
        self.create_main_menu()

    def get_layer_activations(self, img_input):
        if not model:
            return None
        try:
            conv_layers = []
            dense_layers = []
            
            for layer in model.layers:
                class_name = layer.__class__.__name__
                if "Conv2D" in class_name:
                    conv_layers.append(layer)
                elif "Dense" in class_name:
                    dense_layers.append(layer)
            
            target_layers = []
            if len(conv_layers) >= 1: target_layers.append(conv_layers[0])
            if len(conv_layers) >= 2: target_layers.append(conv_layers[1])
            if len(conv_layers) >= 3: target_layers.append(conv_layers[-1]) # Last conv layer
            
            if len(dense_layers) >= 2:
                target_layers.append(dense_layers[0]) # Hidden dense
                target_layers.append(dense_layers[-1]) # Output dense
            elif len(dense_layers) == 1:
                target_layers.append(dense_layers[0]) # Just output
                
            outputs = [layer.output for layer in target_layers]
            activation_model = tf.keras.models.Model(inputs=model.layers[0].input, outputs=outputs)
            activations = activation_model.predict(img_input, verbose=0)
            if not isinstance(activations, list):
                activations = [activations]
            return activations, target_layers
        except Exception as e:
            print(f"Error extracting activations: {e}")
            return None

    def create_gray_photo(self, ch_slice, H, W, zoom):
        min_val = ch_slice.min()
        max_val = ch_slice.max()
        if max_val - min_val > 0.01:
            norm_slice = ((ch_slice - min_val) / (max_val - min_val) * 255).astype(np.uint8)
        else:
            norm_slice = np.zeros_like(ch_slice, dtype=np.uint8)
            
        photo = tk.PhotoImage(width=W, height=H)
        pixels = ""
        for r in range(H):
            row_pixels = []
            for c in range(W):
                val = norm_slice[r, c]
                row_pixels.append(f"#{val:02x}{val:02x}{val:02x}")
            pixels += "{" + " ".join(row_pixels) + "} "
        photo.put(pixels)
        return photo.zoom(int(zoom), int(zoom))

    def start_prediction_animation(self, img_input, prediction):
        if hasattr(self, 'anim_job') and self.anim_job:
            self.after_cancel(self.anim_job)
            self.anim_job = None
            
        self.pred_canvas.delete("all")
        
        self.anim_img_input = img_input
        self.anim_prediction = prediction
        
        # Load activations
        self.anim_activations = None
        self.anim_layers_list = None
        if model:
            res = self.get_layer_activations(img_input)
            if res:
                self.anim_activations, self.anim_layers_list = res
                
        if not self.anim_activations:
            img_2d = img_input[0, :, :, 0]
            base_map = img_2d[1:27, 1:27]
            
            act_conv1 = np.zeros((1, 26, 26, 8))
            for i in range(8):
                if i == 0:
                    map_i = base_map
                elif i == 1:
                    map_i = np.roll(base_map, 1, axis=0)
                elif i == 2:
                    map_i = np.roll(base_map, -1, axis=0)
                elif i == 3:
                    map_i = np.roll(base_map, 1, axis=1)
                elif i == 4:
                    map_i = np.roll(base_map, -1, axis=1)
                elif i == 5:
                    map_i = 1.0 - base_map
                elif i == 6:
                    map_i = base_map * 0.5
                else:
                    map_i = base_map * (np.random.rand(26, 26) * 0.3 + 0.7)
                
                noise = np.random.rand(26, 26) * 0.05
                act_conv1[0, :, :, i] = np.clip(map_i + noise, 0.0, 1.0)
                
            act_output = np.zeros((1, 10))
            act_output[0, prediction] = 0.98
            
            self.anim_activations = [
                act_conv1,
                np.zeros((1, 24, 24, 8)),
                np.zeros((1, 10, 10, 8)),
                np.zeros((1, 32)),
                act_output
            ]
            class MockLayer:
                def get_weights(self):
                    return np.random.rand(32, 10), np.random.rand(10)
            self.anim_layers_list = [MockLayer()]
                
        # Cache the zoomed conv photos once at startup to prevent CPU lag!
        self.cached_conv_photos = {}
        self.conv1_zoom = 2.0  # default fallback
        if self.anim_activations and len(self.anim_activations) >= 5:
            try:
                # Conv 1 (zoom is dynamic based on canvas height!)
                canvas_h = int(self.pred_canvas.winfo_height())
                if canvas_h < 100:
                    canvas_h = int(self.pred_canvas.cget("height"))
                spacing_y = 12
                avail_h = canvas_h - 90
                avail_maps_h = avail_h - (7 * spacing_y)
                act_map1 = self.anim_activations[0]
                H1, W1 = act_map1.shape[1], act_map1.shape[2]
                ideal_zoom = avail_maps_h / (8 * H1)
                self.conv1_zoom = max(2.0, min(3.0, ideal_zoom))
                
                self.cached_conv_photos[0] = []
                for i in range(8):
                    self.cached_conv_photos[0].append(self.create_gray_photo(act_map1[0, :, :, i], H1, W1, self.conv1_zoom))
            except Exception as e:
                print(f"Error caching conv photos: {e}")
                
        # Initialize animation state machine variables
        self.revealed_conv1 = []
        self.revealed_output = []
        
        self.anim_stage = "hidden"
        self.anim_channel = 0
        self.anim_substep = 0
        
        # Start execution loop
        self.tick_prediction_animation()

    def tick_prediction_animation(self):
        if self.current_screen != "prediction" or self.is_paused:
            return
            
        if not self.anim_activations or len(self.anim_activations) < 5:
            # Fallback to instant draw of final result without activations
            self.anim_stage = "final"
            self.draw_current_animation_state()
            return
            
        delay = 10  # Fast sweep delay (10ms)
        
        if self.anim_stage == "hidden":
            if self.anim_channel < 8:
                if self.anim_substep < 675:
                    self.anim_substep = min(675, self.anim_substep + 15)
                else:
                    self.revealed_conv1.append(self.anim_channel)
                    self.anim_channel += 1
                    self.anim_substep = 0
            else:
                self.anim_stage = "output"
                self.anim_channel = 0
                self.anim_substep = 0
                delay = 5  # Immediate transition
                
        elif self.anim_stage == "output":
            if self.anim_channel < 10:
                self.revealed_output.append(self.anim_channel)
                self.anim_channel += 1
                delay = 50  # Visually see each output line draw (50ms)
            else:
                self.anim_stage = "final"
                delay = 5
                self.play_action_sound("select")
                
        self.draw_current_animation_state()
        
        if self.anim_stage != "final":
            self.anim_job = self.after(delay, self.tick_prediction_animation)

    def get_conv_map_center(self, center_x, center_y, zoom, map_idx, H, W, spacing_y=12):
        map_w = W * zoom
        map_h = H * zoom
        cols = 1
        rows = 8
        grid_w = map_w
        grid_h = rows * map_h + (rows - 1) * spacing_y
        
        start_x = center_x - grid_w // 2
        start_y = center_y - grid_h // 2
        
        x = center_x
        y = int(start_y + map_idx * (map_h + spacing_y) + map_h // 2)
        return x, y, map_w, map_h

    def draw_static_conv_grid(self, center_x, center_y, zoom, shape, spacing_y=12):
        H, W = shape
        map_w = W * zoom
        map_h = H * zoom
        cols = 1
        rows = 8
        grid_w = map_w
        grid_h = rows * map_h + (rows - 1) * spacing_y
        
        start_x = center_x - grid_w // 2
        start_y = center_y - grid_h // 2
        
        for i in range(rows):
            x = center_x
            y = int(start_y + i * (map_h + spacing_y) + map_h // 2)
            self.pred_canvas.create_rectangle(x - map_w // 2 - 1, y - map_h // 2 - 1, x + map_w // 2, y + map_h // 2, outline="#2a2a2a", fill="")

    def draw_single_conv_map(self, layer_idx, map_idx, center_x, center_y, zoom, H, W):
        try:
            zoomed_photo = self.cached_conv_photos[layer_idx][map_idx]
            x, y, map_w, map_h = self.get_conv_map_center(center_x, center_y, zoom, map_idx, H, W)
            self.pred_canvas.create_image(x, y, image=zoomed_photo)
            self.pred_canvas.create_rectangle(x - map_w // 2 - 1, y - map_h // 2 - 1, x + map_w // 2, y + map_h // 2, outline="#444444")
        except Exception as e:
            print(f"Error drawing single conv map: {e}")

    def draw_current_animation_state(self):
        self.pred_canvas.delete("all")
        canvas_w = int(self.pred_canvas.cget("width"))
        canvas_h = int(self.pred_canvas.cget("height"))
        
        self.conv_photos = []
        
        col_x = [
            int(canvas_w * 0.15),  # Input
            int(canvas_w * 0.50),  # Hidden Layer
            int(canvas_w * 0.85)   # Output
        ]
        
        headers = ["Input", "Hidden Layer", "Output"]
        for i, header in enumerate(headers):
            self.pred_canvas.create_text(col_x[i], 25, text=header, font=("Helvetica", 16, "bold"), fill="#888888")
            
        # Draw Input Image
        img_2d = (self.anim_img_input[0, :, :, 0] * 255).astype(np.uint8)
        photo = tk.PhotoImage(width=28, height=28)
        pixels = ""
        for r in range(28):
            row_pixels = []
            for c in range(28):
                val = img_2d[r, c]
                row_pixels.append(f"#{val:02x}{val:02x}{val:02x}")
            pixels += "{" + " ".join(row_pixels) + "} "
        photo.put(pixels)
        self.input_photo = photo.zoom(6, 6)
        self.pred_canvas.create_image(col_x[0], canvas_h // 2, image=self.input_photo)
        
        if not self.anim_activations or len(self.anim_activations) < 5:
            self.pred_canvas.create_text(canvas_w // 2, canvas_h // 2, 
                                         text=f"Prediction: {self.anim_prediction}\n(Activations unavailable)", 
                                         font=("Helvetica", 24, "bold"), fill="white")
            return
            
        num_output = 10
        spacing_output = (canvas_h - 100) / num_output
        start_y_output = 50 + spacing_output / 2
        output_coords = [(col_x[2], int(start_y_output + i * spacing_output)) for i in range(num_output)]
        
        # 1. Draw finished connection lines (Input -> Hidden) behind the blocks
        H1, W1 = self.anim_activations[0].shape[1], self.anim_activations[0].shape[2]
        
        # Calculate dynamic hidden layer positioning to start exactly at y = 70 (below header text)
        spacing_y = 12
        grid_h = 8 * (H1 * self.conv1_zoom) + 7 * spacing_y
        hidden_center_y = int(70 + grid_h // 2)
        
        if len(self.revealed_conv1) == 8 or self.anim_stage in ["output", "final"]:
            ix, iy = col_x[0], canvas_h // 2
            for i in range(8):
                tx, ty, _, _ = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, i, H1, W1, spacing_y)
                self.pred_canvas.create_line(ix, iy, tx, ty, fill="#282828", width=1)
                
        # 2. Draw connection lines to Output layer behind the blocks
        if self.anim_stage == "output":
            for node_idx in self.revealed_output:
                out_x, out_y = output_coords[node_idx]
                for i in range(8):
                    sx, sy, _, _ = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, i, H1, W1, spacing_y)
                    self.pred_canvas.create_line(sx, sy, out_x, out_y, fill="#555555", width=1)
        elif self.anim_stage == "final":
            for node_idx in range(10):
                out_x, out_y = output_coords[node_idx]
                for i in range(8):
                    sx, sy, _, _ = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, i, H1, W1, spacing_y)
                    self.pred_canvas.create_line(sx, sy, out_x, out_y, fill="#282828", width=1)
            
            # Glowing winner lines (White, behind blocks!)
            winner_x, winner_y = output_coords[self.anim_prediction]
            for i in range(8):
                sx, sy, _, _ = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, i, H1, W1, spacing_y)
                self.pred_canvas.create_line(sx, sy, winner_x, winner_y, fill="white", width=2)

        # 3. Draw static background structures
        self.draw_static_conv_grid(col_x[1], hidden_center_y, self.conv1_zoom, (H1, W1), spacing_y)
        
        # 4. Draw revealed Conv features on top of connection lines
        for ch in self.revealed_conv1:
            self.draw_single_conv_map(0, ch, col_x[1], hidden_center_y, self.conv1_zoom, H1, W1)
        if self.anim_stage == "hidden" and self.anim_channel < 8:
            self.draw_single_conv_map(0, self.anim_channel, col_x[1], hidden_center_y, self.conv1_zoom, H1, W1)
            row = self.anim_substep // W1
            col = self.anim_substep % W1
            tx, ty, tw, th = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, self.anim_channel, H1, W1, spacing_y)
            mx1, my1 = tx - tw // 2, ty - th // 2
            mx2, my2 = tx + tw // 2, ty + th // 2
            if row + 1 < H1:
                self.pred_canvas.create_rectangle(mx1, my1 + (row + 1) * self.conv1_zoom, mx2, my2, fill="#222222", outline="")
            if col + 1 < W1:
                self.pred_canvas.create_rectangle(mx1 + (col + 1) * self.conv1_zoom, my1 + row * self.conv1_zoom, mx2, my1 + (row + 1) * self.conv1_zoom, fill="#222222", outline="")
                
        # 5. Draw Output Layer circles
        self.draw_output_layer(self.anim_activations[4], self.anim_prediction, output_coords)
        
        # 6. Draw Animation Overlay
        self.draw_animation_overlay(col_x, canvas_h, None, output_coords)

    def draw_output_layer(self, output_act, prediction, coords):
        num_display = len(coords)
        r = 20
        
        for i in range(num_display):
            if i in self.revealed_output:
                prob = float(output_act[0, i])
                is_winner = (i == prediction)
                
                if is_winner:
                    color = "#00E5FF"
                    outline_color = "#FFFFFF"
                    outline_width = 3
                else:
                    color = "#333333"
                    outline_color = "#333333"
                    outline_width = 1
                    
                x, y = coords[i]
                self.pred_canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=outline_color, width=outline_width)
                
                text_color = "black" if is_winner else "white"
                self.pred_canvas.create_text(x, y, text=str(i), font=("Helvetica", 14, "bold"), fill=text_color)
                
                prob_text = f"{int(prob * 100)}%"
                self.pred_canvas.create_text(x + 40, y, text=prob_text, font=("Helvetica", 12, "bold" if is_winner else "normal"), fill="#00E5FF" if is_winner else "#888888", anchor="w")
            else:
                x, y = coords[i]
                self.pred_canvas.create_oval(x - r, y - r, x + r, y + r, fill="#333333", outline="#333333", width=1)
                self.pred_canvas.create_text(x, y, text=str(i), font=("Helvetica", 14, "bold"), fill="#666666")

    def draw_animation_overlay(self, col_x, canvas_h, dense_coords, output_coords):
        if self.anim_stage == "hidden" and self.anim_channel < 8:
            sx, sy = col_x[0], canvas_h // 2
            sw, sh = 168, 168
            kw, kh = 18, 18
            
            row = self.anim_substep // 26
            col = self.anim_substep % 26
            
            bx1 = sx - sw//2 + col * 6
            by1 = sy - sh//2 + row * 6
            bx2 = bx1 + kw
            by2 = by1 + kh
            
            self.pred_canvas.create_rectangle(bx1, by1, bx2, by2, outline="white", width=1)
            
            H, W = self.anim_activations[0].shape[1], self.anim_activations[0].shape[2]
            
            spacing_y = 12
            grid_h = 8 * (H * self.conv1_zoom) + 7 * spacing_y
            hidden_center_y = int(70 + grid_h // 2)
            
            tx, ty, tw, th = self.get_conv_map_center(col_x[1], hidden_center_y, self.conv1_zoom, self.anim_channel, H, W, spacing_y)
            
            px_tl = tx - tw // 2 + col * self.conv1_zoom
            py_tl = ty - th // 2 + row * self.conv1_zoom
            px_br = px_tl + self.conv1_zoom
            py_br = py_tl + self.conv1_zoom
            
            self.pred_canvas.create_line(bx1, by1, px_tl, py_tl, fill="white", width=1)
            self.pred_canvas.create_line(bx2, by2, px_br, py_br, fill="white", width=1)

    # ------------------ COPYCAT GAME LOGIC ------------------
    
    def next_copycat_level(self):
        if self.is_paused:
            return
        self.copycat_state = "showing"
        self.copycat_user_sequence = []
        
        # Reset input number label for the new level
        if hasattr(self, 'cc_input_label') and self.cc_input_label.winfo_exists():
            self.cc_input_label.config(text="Input Number: -", fg="#888888")
        
        self.copycat_timer_left = max(30, 60 - (self.copycat_level - 1) * 5)
        self.cc_timer_label.config(text=f"Time: {self.copycat_timer_left}s")
        self.cc_status_label.config(text=f"Level {self.copycat_level}: Watch the Sequence!")
        
        if len(self.copycat_sequence) < 10:
            self.copycat_sequence.append(random.randint(0, 9))
            
        threading.Thread(target=self.animate_sequence, daemon=True).start()

    def animate_sequence(self):
        for num in self.copycat_sequence:
            if self.current_screen != "copycat" or self.is_paused or self.copycat_state != "showing": return
            self.cc_display_label.config(text=str(num), bg="#555511")
            self.play_action_sound("navigate")  # Sound for computer displaying digit
            time.sleep(0.8)
            if self.current_screen != "copycat" or self.is_paused or self.copycat_state != "showing": return
            self.cc_display_label.config(text="---", bg="#333333")
            time.sleep(0.3)
            
        if self.current_screen == "copycat" and not self.is_paused and self.copycat_state == "showing":
            self.copycat_state = "waiting"
            self.cc_status_label.config(text="Your turn! Replicate the sequence.")
            self.start_copycat_timer()

    def start_copycat_timer(self):
        if self.timer_job:
            self.after_cancel(self.timer_job)
        if self.copycat_state == "waiting" and not self.is_paused:
            if self.copycat_timer_left > 0:
                self.copycat_timer_left -= 1
                self.cc_timer_label.config(text=f"Time: {self.copycat_timer_left}s")
                self.timer_job = self.after(1000, self.start_copycat_timer)
            else:
                self.game_over_copycat("Time's Up!")

    def handle_copycat_input(self, digit):
        if self.copycat_state not in ["showing", "waiting"] or self.is_paused:
            return
            
        self.copycat_user_sequence.append(digit)
        self.cc_display_label.config(text=str(digit), bg="#115511")
        
        # Update input label to show user's current digit input
        if hasattr(self, 'cc_input_label') and self.cc_input_label.winfo_exists():
            self.cc_input_label.config(text=f"Input Number: {digit}", fg="white")
        
        current_step = len(self.copycat_user_sequence) - 1
        if self.copycat_user_sequence[current_step] != self.copycat_sequence[current_step]:
            self.game_over_copycat("Wrong Sequence!")
            return
            
        # User pressed a correct step
        self.play_action_sound("navigate")

        if len(self.copycat_user_sequence) == len(self.copycat_sequence):
            if len(self.copycat_sequence) == 10:
                self.play_action_sound("jackpot")
                self.cc_status_label.config(text="Victory! You completed all 10 stages!")
                self.copycat_state = "game_over"
                if self.timer_job:
                    self.after_cancel(self.timer_job)
                    self.timer_job = None
            else:
                self.play_action_sound("correct")
                self.copycat_level += 1
                self.cc_status_label.config(text="Correct! Getting ready...")
                self.copycat_state = "idle"
                if self.timer_job:
                    self.after_cancel(self.timer_job)
                    self.timer_job = None
                self.copycat_timer_left = max(30, 60 - (self.copycat_level - 1) * 5)
                self.cc_timer_label.config(text=f"Time: {self.copycat_timer_left}s")
                self.transition_job = self.after(2000, self.next_copycat_level)

    def game_over_copycat(self, reason):
        self.play_action_sound("wrong")
        self.copycat_state = "game_over"
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        self.cc_status_label.config(text=f"GAME OVER: {reason}")
        self.cc_display_label.config(text="X", bg="#551111")

    # ---------------- HARDWARE / NAVIGATION CONTROLS ----------------
    
    def handle_command(self, cmd):
        if self.is_paused:
            if cmd in ["select", "o"]: # O SELECT cycles selection
                self.play_action_sound("navigate")
                self.pause_selected_idx = 1 - self.pause_selected_idx
                self.update_pause_highlight()
            elif cmd in ["start", "x", "reset"]: # X ENTER executes selection
                self.play_action_sound("navigate")
                self.execute_pause_option()
            return

        if self.current_screen == "menu":
            if cmd in ["select", "o", "down", "right"]: # O SELECT or down/right cycles menu forward
                self.play_action_sound("navigate")
                self.selected_menu_idx = (self.selected_menu_idx + 1) % 3
                self.update_menu_highlight()
            elif cmd in ["up", "left"]: # up/left cycles menu backward
                self.play_action_sound("navigate")
                self.selected_menu_idx = (self.selected_menu_idx - 1) % 3
                self.update_menu_highlight()
            elif cmd in ["start", "x"]: # X ENTER enters menu item
                if self.selected_menu_idx == 0: self.start_number_prediction()
                elif self.selected_menu_idx == 1: self.start_copycat()
                elif self.selected_menu_idx == 2: self.start_config()
                
        elif self.current_screen == "config":
            if cmd in ["select", "o"]: # O SELECT cycles config buttons
                self.play_action_sound("navigate")
                self.config_selected_idx = (self.config_selected_idx + 1) % 3
                self.update_config_highlight()
            elif cmd in ["start", "x"]: # X ENTER executes config button
                self.play_action_sound("navigate")
                if self.config_selected_idx == 0:
                    self.decrease_volume()
                elif self.config_selected_idx == 1:
                    self.increase_volume()
                elif self.config_selected_idx == 2:
                    self.save_and_return_config()
            elif cmd in ["up", "right"]: # Directly change volume
                self.increase_volume()
            elif cmd in ["down", "left"]: # Directly change volume
                self.decrease_volume()

        elif self.current_screen in ["prediction", "copycat"]:
            if cmd in ["select", "o", "pause"]: # O SELECT opens pause menu
                self.show_pause_menu()
            elif cmd in ["x", "reset"]: # X ENTER resets
                if self.current_screen == "copycat":
                    self.start_copycat()
                elif self.current_screen == "prediction":
                    self.create_main_menu()
            elif cmd == "start" and self.current_screen == "copycat" and self.copycat_state == "game_over":
                self.start_copycat() 

    def show_pause_menu(self):
        self.play_action_sound("navigate")
        self.is_paused = True
        self.pause_selected_idx = 0 
        
        self.pause_overlay = tk.Frame(self, bg="#111111")
        self.pause_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        container = tk.Frame(self.pause_overlay, bg="#111111")
        container.pack(expand=True)
        
        tk.Label(container, text="PAUSED", font=("Helvetica", 48, "bold"), bg="#111111", fg="white").pack(pady=40)
        
        self.pause_btn_resume = tk.Button(container, text="Resume", font=("Helvetica", 20), width=25, height=2, bg="#333333", fg="white")
        self.pause_btn_resume.pack(pady=15)
        
        self.pause_btn_home = tk.Button(container, text="Return to Home Menu", font=("Helvetica", 20), width=25, height=2, bg="#333333", fg="white")
        self.pause_btn_home.pack(pady=15)
        
        self.update_pause_highlight()

    def update_pause_highlight(self):
        for idx, btn in enumerate([self.pause_btn_resume, self.pause_btn_home]):
            if idx == self.pause_selected_idx:
                btn.config(bg="#FFCC00", fg="black")
            else:
                btn.config(bg="#333333", fg="white")

    def execute_pause_option(self):
        overlay = self.pause_overlay
        self.pause_overlay = None
        self.is_paused = False
        
        if overlay is not None:
            overlay.destroy()
        
        if self.pause_selected_idx == 0:
            if self.current_screen == "copycat":
                if self.copycat_state == "waiting":
                    self.start_copycat_timer()
                elif self.copycat_state == "showing":
                    self.animate_sequence()
        else:
            self.create_main_menu()

    # ---------------- THREAD SAFE PROCESSING ----------------
    
    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "PRED":
                    prediction, img_input = data
                    if self.current_screen == "prediction" and not self.is_paused:
                        self.start_prediction_animation(img_input, prediction)
                    elif self.current_screen == "copycat" and not self.is_paused:
                        self.handle_copycat_input(prediction)
                elif msg_type == "CMD":
                    self.handle_command(data)
                self.queue.task_done()
        except queue.Empty:
            pass
        self.after(50, self.check_queue)

    # ---------------- BACKEND SERIAL RUNNER ----------------
    
    def serial_listener(self):
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                print(f"Listening on port {SERIAL_PORT}...")
                while self.is_listening:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue
                    
                    if line.startswith("[DATA]"):
                        raw = line.replace("[DATA] ", "")
                        if len(raw) == PAYLOAD_SIZE * 2:
                            try:
                                img_flat = np.frombuffer(bytes.fromhex(raw), dtype=np.uint8)
                                img_2d = img_flat.reshape((GRID_SIZE, GRID_SIZE))
                                img_normalized = img_2d.astype("float32") / 255.0
                                img_input = img_normalized.reshape(1, GRID_SIZE, GRID_SIZE, 1)
                                
                                if model:
                                    prediction = int(np.argmax(model.predict(img_input, verbose=0)))
                                else:
                                    prediction = random.randint(0, 9)
                                    
                                self.queue.put(("PRED", (prediction, img_input)))
                            except Exception as infer_err:
                                print(f"Inference error: {infer_err}")
                        else:
                            print("Error: Packet timed out or was incomplete")
                            
                    elif line.startswith("[CMD]"):
                        cmd = line.replace("[CMD] ", "").lower()
                        self.queue.put(("CMD", cmd))
                        
        except serial.SerialException as e:
            print(f"Error accessing serial port: {e}")


if __name__ == "__main__":
    app = App()
    app.mainloop()