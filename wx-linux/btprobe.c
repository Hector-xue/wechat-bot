#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <execinfo.h>

static ssize_t (*real_pwrite64)(int, const void *, size_t, off_t) = NULL;
static int n = 0;

static int db_path(int fd, char *out, size_t len) {
    char link[64], target[512];
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
    ssize_t r = readlink(link, target, sizeof(target)-1);
    if (r <= 0) return 0;
    target[r] = 0;
    if (!strstr(target, "db_storage")) return 0;
    snprintf(out, len, "%s", target);
    return 1;
}

ssize_t pwrite64(int fd, const void *buf, size_t count, off_t offset) {
    if (!real_pwrite64) real_pwrite64 = dlsym(RTLD_NEXT, "pwrite64");
    char p[256];
    if (count >= 1024 && n < 3 && db_path(fd, p, sizeof(p))) {
        n++;
        void *bt[40];
        int k = backtrace(bt, 40);
        int f = open("/root/dsh/wx-linux/logs/bt.log", O_WRONLY|O_APPEND|O_CREAT, 0666);
        if (f >= 0) {
            char line[128];
            int l = snprintf(line, sizeof(line), "=== write %s off=%lld count=%zu\n", p, (long long)offset, count);
            ssize_t w = write(f, line, l); (void)w;
            for (int i = 0; i < k; i++) {
                l = snprintf(line, sizeof(line), "  #%d 0x%lx\n", i, (unsigned long)bt[i]);
                w = write(f, line, l); (void)w;
            }
            close(f);
        }
    }
    return real_pwrite64(fd, buf, count, offset);
}
