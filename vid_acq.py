import sys
import cv2
import numpy as np
import socket
import os
import time
import pickle
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QFileDialog, QDesktopWidget
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap

# Configurable variables
UDP_LISTEN_PORT = 12345
DATA_ROOT = 'C://Users//ranso//Videos//'  # Change as needed to your data root
ASPECT_RATIO = 4 / 3  # Assuming aspect ratio of the cameras is 4:3
CAMERAS = [1,0]  # List of camera indices to acquire and in what order

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
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)
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
            self.arduino = serial.Serial('COM3', 9600)
        except (ImportError, serial.SerialException):
            self.arduino = DummyArduino()
        self.arduino.write(b'L')  # Set Arduino to low at startup

    def initUI(self):
        self.image_label = QLabel(self)
        self.record_button = QPushButton('Start Recording', self)
        self.record_button.clicked.connect(self.toggle_recording)
        
        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.record_button)
        self.setLayout(layout)
        
        self.setWindowTitle('Dual Camera Capture')
        self.resize_window()
        self.show()

    def resize_window(self):
        screen_rect = QDesktopWidget().screenGeometry()
        screen_height = int(screen_rect.height() * 0.8)  # Make the window 20% smaller
        screen_width = int(screen_rect.width() * 0.8)  # Make the window 20% smaller

        num_cameras = len(self.cameras)
        aspect_ratio = ASPECT_RATIO

        # Calculate the appropriate height while respecting aspect ratio
        window_height = screen_height // num_cameras
        window_width = int(window_height * aspect_ratio)

        if window_width > screen_width:
            window_width = screen_width
            window_height = int(window_width / aspect_ratio)

        window_height *= num_cameras  # Account for the number of cameras stacked vertically

        self.setGeometry(int((screen_rect.width() - window_width) // 2),
                         int((screen_rect.height() - window_height) // 2),
                         int(window_width), int(window_height))

        print(f"Window dimensions: {window_width}x{window_height}")

    def update_frame(self):
        frames = []
        for capture in self.captures:
            ret, frame = capture.read()
            if ret:
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frames.append(frame_gray)

        if len(frames) == len(self.captures):
            resized_frames = [self.resize_with_aspect_ratio(frame, 640, 480) for frame in frames]
            combined_frame = np.vstack(resized_frames)

            # Update the FPS calculation
            current_time = time.time()
            self.fps = 1.0 / (current_time - self.last_time)
            self.last_time = current_time

            # Convert the grayscale frame to a 3-channel image for colored text overlay
            display_frame = cv2.cvtColor(combined_frame, cv2.COLOR_GRAY2BGR)
            
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
                self.out.write(combined_frame)
                self.frame_count += 1
                self.frame_data['frame_count'] = self.frame_count
                frame_time = current_time - self.start_time
                self.frame_data['frame_times'].append(frame_time)
                if self.frame_count % 100 == 0:
                    self.toggle_arduino_output()


    def resize_with_aspect_ratio(self, image, width, height, inter=cv2.INTER_AREA):
        h, w = image.shape[:2]
        aspect_ratio = w / h

        if aspect_ratio > 1:  # Landscape orientation
            new_w = width
            new_h = int(width / aspect_ratio)
        else:  # Portrait orientation or square
            new_h = height
            new_w = int(height * aspect_ratio)

        resized_image = cv2.resize(image, (new_w, new_h), interpolation=inter)

        # Padding to target dimensions
        pad_top = (height - new_h) // 2
        pad_bottom = height - new_h - pad_top
        pad_left = (width - new_w) // 2
        pad_right = width - new_w - pad_left

        padded_image = cv2.copyMakeBorder(resized_image, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_CONSTANT, value=[0, 0, 0])

        return padded_image

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
        frames = []
        for capture in self.captures:
            ret, frame = capture.read()
            if ret:
                frames.append(frame)
        if len(frames) == len(self.captures):
            resized_frames = [self.resize_with_aspect_ratio(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 640, 480) for frame in frames]
            height, width = resized_frames[0].shape  # Assuming all frames have the same size after resizing
            combined_height = height * len(self.captures)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.final_filename, fourcc, 20.0, (width, combined_height), isColor=False)
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
            save_dir = os.path.join(self.data_root, experiment_id[-7:], experiment_id)
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
