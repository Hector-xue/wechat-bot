# 编译 C 工具（可选）
# memscan 需要 OpenSSL 开发头（openssl-devel / libssl-dev）
CC      = gcc
CFLAGS  = -O2 -Wall

all: memscan btprobe.so sniffer.so memcpy_probe.so

# 内存扫描器：定位 SQLCipher 密钥候选（依赖 OpenSSL AES/HMAC/EVP）
memscan: memscan.c
	$(CC) $(CFLAGS) -o $@ $< -lcrypto

# LD_PRELOAD 探针：backtrace / dlsym 钩子
btprobe.so: btprobe.c
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $<

# LD_PRELOAD 拦截库：pread 抓明文页 + pwrite 抓调用栈
sniffer.so: sniffer.c
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $<

memcpy_probe.so: memcpy_probe.c
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $<

clean:
	rm -f memscan memscan2 memscan3 memscan4 memscan5 memscan6 memscan7 \
	      btprobe.so sniffer.so sniffer_w.so memcpy_probe.so

.PHONY: all clean
