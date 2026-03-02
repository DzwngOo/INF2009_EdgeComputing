import queue, threading, cv2

def gui_loop(
    display_q: queue.Queue, 
    stop_evt: threading.Event, 
    window_name: str = "YOLO"
):
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    while not stop_evt.is_set():
        try:
            frame = display_q.get(timeout=0.05)
        except queue.Empty:
            frame = None

        if frame is not None:
            cv2.imshow(window_name, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            stop_evt.set()
            break

    cv2.destroyAllWindows()
