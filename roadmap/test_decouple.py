from decouple import config
print("DB_ENGINE is:", repr(config('DB_ENGINE', default='').strip()))
import urllib.request
import time
print("Finished!")
