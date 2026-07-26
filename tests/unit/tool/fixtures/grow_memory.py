"""T005: 持续分配内存——用于触发 POSIX 资源超限（RLIMIT_AS）。

仅供 POSIX 平台的资源超限测试使用；Windows 测试中不会执行到这个脚本。
"""

import sys

if __name__ == "__main__":
    chunks = []
    try:
        while True:
            # 每次分配 10MB，持续增长直至触发 RLIMIT_AS（进程被 SIGKILL）
            chunks.append(bytearray(10 * 1024 * 1024))
    except MemoryError:
        sys.exit(1)
