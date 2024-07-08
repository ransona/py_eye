import sys
import cv2
import numpy as np
import socket
import os
import time
import pickle
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QFileDialog, QDesktopWidget, QSizePolicy
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap

# Configurable variables
UDP_LISTEN_PORT = 1813
DATA_ROOT = 'C://local_repository//'  # Change as needed to your data root
CAMERAS = [0, 1]  # List of camera indices to acquire and in what order
ARDUINO_PORT = 'COM4'  # Change as needed to your Arduino port
DESIRED_FPS = 30

# Display size
DISP_WIDTH = 350
DISP_HEIGHT = 350

# Save size
SAVE_WIDTH = 744
SAVE_HEIGHT = 480

class DummyArduino:
    def write(self, data):
        print(f"Dummy Arduino received data: {data}")

class UDPListener(QThread):
    udp_signal = pyqtSignal(str)

    def __init__(self, port=UDP_LISTEN_PORT):
        super().__init__()
        self.port = port
        self.running = True
        self.sock = None

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.settimeout(1.0)  # Set a timeout for the socket operations

        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
                message = data.decode('utf-8')
                self.udp_signal.emit(message)
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()
        self.wait()

class CameraApp(QWidget):
    def __init__(self):
        super().__init__()
        self.data_root = DATA_ROOT
        self.cameras = CAMERAS
        self.initUI()
        self.captures = [cv2.VideoCapture(cam, cv2.CAP_DSHOW) for cam in self.cameras]

        # Set the frame rate for each camera
        for i, capture in enumerate(self.captures):
            capture.set(cv2.CAP_PROP_FPS, DESIRED_FPS)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(int(1000 / DESIRED_FPS))
        self.recording = False
        self.frame_count = 0
        self.final_filename = None
        self.last_time = time.time()
        self.fps = 0
        self.frame_data = {'frame_count': 0, 'frame_times': []}
        self.experiment_id = None
        self.acquisition_start_time = None

        self.udp_listener = UDPListener()
        self.udp_listener.udp_signal.connect(self.handle_udp_message)
        self.udp_listener.start()

        # Arduino setup
        try:
            import serial
            self.arduino = serial.Serial(ARDUINO_PORT, 9600)
            print('Arduino detected')
        except (ImportError, serial.SerialException):
            self.arduino = DummyArduino()
        self.arduino.write(b'L')  # Set Arduino to low at startup

    def initUI(self):
        self.image_label = QLabel(self)
        label_width = DISP_WIDTH
        label_height = DISP_HEIGHT * len(self.cameras)
        self.image_label.setFixedSize(label_width, label_height)  # Set the QLabel size
        self.image_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.image_label.setAlignment(Qt.AlignCenter)

        self.record_button = QPushButton('Start Recording', self)
        self.record_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.record_button.clicked.connect(self.toggle_recording)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.record_button)
        self.setLayout(layout)

        self.setWindowTitle('Camera Capture')
        self.adjust_window_size()
        self.show()
        self.adjustSize()  # Automatically resize to fit the contents

    def adjust_window_size(self):
        screen_rect = QDesktopWidget().screenGeometry(self)
        window_width = DISP_WIDTH
        window_height = DISP_HEIGHT * len(self.cameras)

        self.setGeometry(
            (screen_rect.width() - window_width) // 2,
            (screen_rect.height() - window_height) // 2,
            window_width,
            window_height
        )

    def update_frame(self):
        frames_disp = []
        frames_save = []
        for capture in self.captures:
            ret, frame = capture.read()
            if ret:
                resized_frame_disp = cv2.resize(frame, (DISP_WIDTH, DISP_HEIGHT))
                resized_frame_save = cv2.resize(frame, (SAVE_WIDTH, SAVE_HEIGHT))
                frames_disp.append(cv2.cvtColor(resized_frame_disp, cv2.COLOR_BGR2GRAY))
                frames_save.append(cv2.cvtColor(resized_frame_save, cv2.COLOR_BGR2GRAY))

        if len(frames_disp) < 3:
            for _ in range(3 - len(frames_disp)):
                frames_disp.append(np.zeros((DISP_HEIGHT, DISP_WIDTH), dtype=np.uint8))
                frames_save.append(np.zeros((SAVE_HEIGHT, SAVE_WIDTH), dtype=np.uint8))

        combined_frame_display = np.vstack(frames_disp)
        combined_frame_save = np.hstack(frames_save)

        # Update the FPS calculation
        current_time = time.time()
        self.fps = 1.0 / (current_time - self.last_time)
        self.last_time = current_time

        # Convert the grayscale frame to a 3-channel image for colored text overlay
        display_frame = cv2.cvtColor(combined_frame_display, cv2.COLOR_GRAY2BGR)

        # Overlay the FPS and status text on the display frame
        display_frame = cv2.putText(display_frame, f'FPS: {self.fps:.2f}', (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        status_text = "RECORDING" if self.recording else "IDLE"
        status_color = (0, 0, 255) if self.recording else (0, 255, 0)
        display_frame = cv2.putText(display_frame, status_text, (10, 50),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1, cv2.LINE_AA)

        if self.recording and self.experiment_id:
            display_frame = cv2.putText(display_frame, f'Experiment ID: {self.experiment_id}', (10, 70),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            elapsed_time = time.time() - self.acquisition_start_time
            elapsed_time_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_time)) + f":{int((elapsed_time % 1) * 100):02d}"
            display_frame = cv2.putText(display_frame, f'Elapsed Time: {elapsed_time_str}', (10, 90),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

            if self.frame_count >= 100:
                interframe_intervals = np.diff(self.frame_data['frame_times'][-100:])
                if len(interframe_intervals) > 0:
                    avg_interframe_interval = np.mean(interframe_intervals) * 1000  # Convert to milliseconds
                    std_interframe_interval = np.std(interframe_intervals) * 1000  # Convert to milliseconds
                    display_frame = cv2.putText(display_frame,
                                                f'Avg Interframe: {avg_interframe_interval:.2f}ms +/- {std_interframe_interval:.2f}ms',
                                                (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        self.display_image(display_frame)

        if self.recording:
            self.out.write(combined_frame_save)
            self.frame_count += 1
            self.frame_data['frame_count'] = self.frame_count
            frame_time = current_time - self.start_time
            self.frame_data['frame_times'].append(frame_time)
            if self.frame_count % 100 == 0:
                self.toggle_arduino_output()

    def display_image(self, frame):
        qformat = QImage.Format_RGB888
        img = QImage(frame, frame.shape[1], frame.shape[0], frame.strides[0], qformat)
        self.image_label.setPixmap(QPixmap.fromImage(img))
        self.image_label.setScaledContents(True)

    def toggle_recording(self):
        if self.recording:
            self.recording = False
            self.record_button.setText('Start Recording')
            self.out.release()
            self.save_frame_data()
            self.arduino.write(b'L')  # Set Arduino to low after stopping recording
            self.experiment_id = None
        else:
            options = QFileDialog.Options()
            options |= QFileDialog.DontUseNativeDialog
            filename, _ = QFileDialog.getSaveFileName(self, "Save Video As", "", "Video Files (*.mp4);;All Files (*)", options=options)
            if filename:
                if not filename.endswith('.mp4'):
                    filename += '.mp4'
                self.start_recording(filename)

    def start_recording(self, filename):
        self.recording = True
        self.record_button.setText('Stop Recording')
        self.final_filename = filename
        height, width = SAVE_HEIGHT, SAVE_WIDTH * 3  # Combined width for 3 cameras
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.out = cv2.VideoWriter(self.final_filename, fourcc, 20.0, (width, height), isColor=False)
        self.frame_data = {'frame_count': 0, 'frame_times': []}
        self.start_time = time.time()
        self.acquisition_start_time = time.time()
        self.arduino.write(b'L')  # Set Arduino to low at the start of recording

    def handle_udp_message(self, message):
        command = message[:4]
        experiment_id = message[5:]
        if command == "STOP":
            if self.recording:
                self.toggle_recording()
        elif command == "GOGO":
            self.experiment_id = experiment_id
            save_dir = os.path.join(self.data_root, experiment_id[14:], experiment_id)
            os.makedirs(save_dir, exist_ok=True)
            filename = os.path.join(save_dir, f"{experiment_id}_eye1.mp4")
            self.start_recording(filename)

    def toggle_arduino_output(self):
        self.arduino.write(b'T')  # Dummy command to toggle digital output

    def save_frame_data(self):
        if self.final_filename:
            meta_filename = self.final_filename.replace('_eye1.mp4', '_eyeMeta1.pickle')
            with open(meta_filename, 'wb') as f:
                pickle.dump(self.frame_data, f)

    def closeEvent(self, event):
        self.timer.stop()
        self.udp_listener.stop()
        for capture in self.captures:
            capture.release()
        if self.recording:
            self.out.release()
        if hasattr(self.arduino, 'close'):
            self.arduino.close()
        event.accept()  # Ensure the event is accepted to close the application

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = CameraApp()
    sys.exit(app.exec_())
