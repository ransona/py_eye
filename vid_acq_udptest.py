import socket

def send_udp_message(message, address="127.0.0.1", port=12345):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode('utf-8'), (address, port))
    sock.close()

if __name__ == "__main__":
    # Example usage:
    expID = '2016-10-14_09_CFAP049'
    udp_command = 'GOGO'
    send_udp_message(udp_command+'*'+expID)  # Start recording
    input("Press Enter to stop recording...")
    send_udp_message("STOP")  # Stop recording
