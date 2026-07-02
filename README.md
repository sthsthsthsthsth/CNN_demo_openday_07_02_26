## ⚡ 1. Neural Network Prediction & Visualization Engine

### 🔍 Real-Time Inference Pipeline
The server establishes serial communication channel using `pyserial` to consume real-time stream data from an external **3.5-inch ESP32-32E Display2** drawing board. 
* **Coordinate Reconstruction:** Raw touchscreen coordinate inputs are dynamically scaled, normalized, and mapped onto a standard $28 \\times 28$ grayscale grid.
* **Model Inference:** The reconstructed matrix is fed into a custom Convolutional Neural Network trained on the **MNIST dataset** to perform immediate classification.

### 🎨 Explainable AI (XAI) Visualization
The interface features a live, step-by-step pipeline animation:
* **Convolution Sweeps:** Displays pixel-by-pixel spatial kernel sweeps directly over the user's drawing.
* **Feature Map Activation:** Animates how the input propagates into the **Hidden Convolutional Layers**, exposing feature maps (edge detectors, orientation filters) as they are computed.
* **Dense Classifier Mapping:** Visualizes the fully-connected weights mapping directly to the final **Output Classifier Layer**, highlighting the winning class dynamically.

---

## 🎮 2. The Copycat Game (Cognitive Memory Challenge)

An interactive, multi-sensory gamification module designed to test memory capacity while showcasing real-time recognition accuracy.

### 🕹️ Core Gameplay Mechanics
1. **The Sequence:** The engine generates a pseudo-random sequence of digits, expanding by one additional digit at every stage across **10 progressively difficult levels**.
2. **The Rehearsal:** The user must replicate the sequence chronologically by sketching each corresponding digit on the ESP32 touchscreen hardware.
3. **The Validation:** The CNN validates each drawing in real-time. If the prediction matches the expected index in the sequence, the user advances.

### 🏆 Reward State
* **Victory State:** Successfully surviving through all 10 stages triggers a programmatic milestone event, playing a synchronized **victory jackpot audio cue** and displaying performance analytics.

---

## 🛠️ Tech Stack & Hardware Requirements
* **Microcontroller:** ESP32-32E Display2 (3.5-inch resistive/capacitive touch screen)
* **Communication Layer:** `pyserial` (Python Serial Port Extension)
* **Deep Learning Framework:** PyTorch / TensorFlow (MNIST-trained model)
* **Visualization Engine:** Custom GUI wrapper (Pygame / PyQt / Tkinter or Web-based dashboard)
