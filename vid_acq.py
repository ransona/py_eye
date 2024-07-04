import sys
import cv2
import numpy as np
import socket
import os
import time
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QFileDialog
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

class DummyArduino:
    def write(self, data):
        print(f"Dummy Arduino received data: {data}")

class UDPListener(QThread):
    udp_signal = pyqtSignal(str)
    
    def __init__(self, port=12345):
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
        self.data_root = 'C://Users//ranso//Videos//'  # Change as needed to your data root
        self.initUI()
        self.capture1 = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.capture2 = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)
        self.recording = False
        self.frame_count = 0
        self.final_filename = None
        self.last_time = time.time()
        self.fps = 0

        self.udp_listener = UDPListener()
        self.udp_listener.udp_signal.connect(self.handle_udp_message)
        self.udp_listener.start()

        # Arduino setup
        try:
            import serial
            self.arduino = serial.Serial('COM3', 9600)
        except (ImportError, serial.SerialException):
            self.arduino = DummyArduino()

    def initUI(self):
        self.image_label = QLabel(self)
        self.record_button = QPushButton('Start Recording', self)
        self.record_button.clicked.connect(self.toggle_recording)
        
        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.record_button)
        self.setLayout(layout)
        
        self.setWindowTitle('Dual Camera Capture')
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(400, 300)
        self.show()

    def update_frame(self):
        ret1, frame1 = self.capture1.read()
        ret2, frame2 = self.capture2.read()

        if ret1 and ret2:
            frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
            frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

            frame1_resized, frame2_resized = self.resize_frames(frame1_gray, frame2_gray)
            combined_frame = np.vstack((frame1_resized, frame2_resized))

            # Update the FPS calculation
            current_time = time.time()
            self.fps = 1.0 / (current_time - self.last_time)
            self.last_time = current_time

            # Convert the grayscale frame to a 3-channel image for colored text overlay
            display_frame = cv2.cvtColor(combined_frame, cv2.COLOR_GRAY2BGR)
            
            # Overlay the FPS and status text on the display frame
            display_frame = cv2.putText(display_frame, f'FPS: {self.fps:.2f}', (10, 30), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
            status_text = "RECORDING" if self.recording else "IDLE"
            status_color = (0, 0, 255) if self.recording else (0, 255, 0)
            display_frame = cv2.putText(display_frame, status_text, (10, 60), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2, cv2.LINE_AA)

            self.display_image(display_frame)
            
            if self.recording:
                self.out.write(combined_frame)
                self.frame_count += 1
                if self.frame_count % 10 == 0:
                    self.toggle_arduino_output()

    def resize_frames(self, frame1, frame2):
        # Resize frames to a common size, maintaining aspect ratio and padding with black borders if necessary
        target_width = 640  # Change as needed
        target_height = 480  # Change as needed

        frame1_resized = self.resize_with_aspect_ratio(frame1, target_width, target_height)
        frame2_resized = self.resize_with_aspect_ratio(frame2, target_width, target_height)

        return frame1_resized, frame2_resized

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
        ret1, frame1 = self.capture1.read()  # Get the frame size
        ret2, frame2 = self.capture2.read()  # Get the frame size
        if ret1 and ret2:
            frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
            frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
            frame1_resized, frame2_resized = self.resize_frames(frame1_gray, frame2_gray)
            height, width = frame1_resized.shape  # Assuming both frames have the same size after resizing
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.final_filename, fourcc, 20.0, (width, height * 2), isColor=False)

    def handle_udp_message(self, message):
        if message.lower() == "stop":
            if self.recording:
                self.toggle_recording()
        else:
            self.start_recording(message)

    def toggle_arduino_output(self):
        self.arduino.write(b'T')  # Dummy command to toggle digital output

    def closeEvent(self, event):
        self.timer.stop()
        self.udp_listener.stop()
        self.capture1.release()
        self.capture2.release()
        if self.recording:
            self.out.release()
        if hasattr(self.arduino, 'close'):
            self.arduino.close()
        event.accept()  # Ensure the event is accepted to close the application

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = CameraApp()
    sys.exit(app.exec_())
