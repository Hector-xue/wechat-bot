#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
static void *(*real_memcpy)(void *, const void *, size_t) = NULL;
static pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
static int n = 0;
void *memcpy(void *d, const void *s, size_t c) {
    if (!real_memcpy) real_memcpy = dlsym(RTLD_NEXT, "memcpy");
    if (c >= 1024 && c <= 8192) {
        const unsigned char *b = (const unsigned char *)s;
        if (b[0] == 0x0d || b[0] == 0x05 || b[0] == 0x0a || b[0] == 0x02 || b[0] == 0x53) {
            pthread_mutex_lock(&mtx);
            if (n < 30) {
                n++;
                int f = open("/root/dsh/wx-linux/logs/memcpy.log", O_WRONLY|O_APPEND|O_CREAT, 0666);
                if (f >= 0) { char line[128];
                    int l = snprintf(line, sizeof(line), "size=%zu head=%02x%02x%02x%02x\n", c, b[0],b[1],b[2],b[3]);
                    ssize_t w = write(f, line, l); (void)w; close(f); }
            }
            pthread_mutex_unlock(&mtx);
        }
    }
    return real_memcpy(d, s, c);
}
