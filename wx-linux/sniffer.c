// 微信数据库拦截库：读页抓明文 + 写库抓调用栈
#define _GNU_SOURCE
#include <dlfcn.h>
#include <execinfo.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static ssize_t (*real_pread64)(int, void *, size_t, off_t) = NULL;
static ssize_t (*real_pwrite64)(int, const void *, size_t, off_t) = NULL;
static __thread void *pbuf = NULL;
static __thread size_t pcnt = 0;
static __thread off_t poff = 0;
static __thread char ppath[256];
static pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
static int counter = 0;
static int bt_n = 0;

static int db_path(int fd, char *out, size_t n) {
    char link[64], target[512];
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
    ssize_t r = readlink(link, target, sizeof(target) - 1);
    if (r <= 0) return 0;
    target[r] = 0;
    if (!strstr(target, "db_storage")) return 0;
    snprintf(out, n, "%s", target);
    return 1;
}

static void dump_pending(void) {
    if (!pbuf) return;
    void *b = pbuf; size_t c = pcnt; off_t o = poff;
    pbuf = NULL;
    pthread_mutex_lock(&mtx);
    int idx = ++counter;
    pthread_mutex_unlock(&mtx);
    char fn[256];
    snprintf(fn, sizeof(fn), "/root/dsh/wx-linux/logs/pages/%d_%06d.bin", (int)getpid(), idx);
    int f = open(fn, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (f < 0) return;
    size_t want = c < 4096 ? c : 4096;
    ssize_t w = write(f, b, want); (void)w;
    close(f);
    int m = open("/root/dsh/wx-linux/logs/pages_meta.jsonl", O_WRONLY | O_APPEND | O_CREAT, 0666);
    if (m >= 0) {
        char meta[512];
        int len = snprintf(meta, sizeof(meta),
            "{\"file\":\"%d_%06d.bin\",\"db\":\"%s\",\"offset\":%lld,\"head\":\"%02x%02x%02x%02x\"}\n",
            (int)getpid(), idx, ppath, (long long)o,
            ((unsigned char *)b)[0], ((unsigned char *)b)[1],
            ((unsigned char *)b)[2], ((unsigned char *)b)[3]);
        ssize_t w2 = write(m, meta, len); (void)w2;
        close(m);
    }
}

ssize_t pread64(int fd, void *buf, size_t count, off_t offset) {
    if (!real_pread64) real_pread64 = dlsym(RTLD_NEXT, "pread64");
    dump_pending();
    ssize_t r = real_pread64(fd, buf, count, offset);
    if (r > 0 && count >= 1024) {
        char p[256];
        if (db_path(fd, p, sizeof(p))) {
            pbuf = buf; pcnt = count; poff = offset;
            snprintf(ppath, sizeof(ppath), "%s", p);
        }
    }
    return r;
}

ssize_t pwrite64(int fd, const void *buf, size_t count, off_t offset) {
    if (!real_pwrite64) real_pwrite64 = dlsym(RTLD_NEXT, "pwrite64");
    char p[256];
    if (count >= 1024 && db_path(fd, p, sizeof(p))) {
        pthread_mutex_lock(&mtx);
        int slot = bt_n++;
        pthread_mutex_unlock(&mtx);
        if (slot < 3) {
            void *bt[40];
            int k = backtrace(bt, 40);
            int f = open("/root/dsh/wx-linux/logs/bt.log", O_WRONLY | O_APPEND | O_CREAT, 0666);
            if (f >= 0) {
                char line[160];
                int l = snprintf(line, sizeof(line), "=== write off=%lld count=%zu\n", (long long)offset, count);
                ssize_t w = write(f, line, l); (void)w;
                for (int i = 0; i < k; i++) {
                    l = snprintf(line, sizeof(line), "  #%d 0x%lx\n", i, (unsigned long)bt[i]);
                    w = write(f, line, l); (void)w;
                }
                close(f);
            }
        }
    }
    return real_pwrite64(fd, buf, count, offset);
}
