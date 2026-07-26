"""T003: 故意长时间运行——用于触发超时（不读取 stdin）。"""

import sys
import time

if __name__ == "__main__":
    time.sleep(3600)
    sys.exit(0)
