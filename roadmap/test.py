import os
import sys
import time
import threading
import collections
import traceback

trace_log = collections.deque(maxlen=20)
def trace_calls(frame, event, arg):
    if event == "line":
        # only keep track of roadmap module to avoid standard library spam if possible
        # but just in case, track everything
        fn = frame.f_code.co_filename
        if "site-packages" not in fn:
            trace_log.append(f"{fn}:{frame.f_lineno} in {frame.f_code.co_name}")
    return trace_calls

def dumper():
    while True:
        time.sleep(2)
        with open("trace_tail.log", "w", encoding="utf-8") as f:
            f.write("\n".join(trace_log))
            
t = threading.Thread(target=dumper, daemon=True)
t.start()

sys.settrace(trace_calls)

def main():
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'roadmap.settings')
        print("Starting django setup...")
        django.setup()
        print('Django setup ok!')
    except BaseException as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
