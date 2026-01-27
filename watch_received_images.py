from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from receipt_generator import make_receipt
import time
import os

WATCH_DIR = "received_images"

class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        if event.src_path.lower().endswith((".jpg", ".jpeg", ".png")):
            print(f"📸 New image detected: {event.src_path}")

            # Small delay to ensure file write is complete
            time.sleep(0.5)

            make_receipt(event.src_path)

if __name__ == "__main__":
    os.makedirs(WATCH_DIR, exist_ok=True)

    observer = Observer()
    observer.schedule(ImageHandler(), WATCH_DIR, recursive=False)
    observer.start()

    print(f"👀 Watching folder: {WATCH_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
